# Databricks notebook source
# MAGIC %md
# MAGIC # Stage 2 — Load Raw
# MAGIC
# MAGIC Loads every file the schema gate accepted into a **Raw** Delta table, one table per source
# MAGIC (`raw.projects`, `raw.monitoring`).
# MAGIC
# MAGIC **Raw means "as received":**
# MAGIC - Every value is kept exactly as text. No types, no cleaning, no filtering. That happens in Stage 3.
# MAGIC - Column names are switched to the contract's `target` names (e.g. `Total IFC investment as approved by
# MAGIC   Board(Million - USD)` becomes `total_approved_musd`). Delta tables don't accept spaces or brackets in
# MAGIC   column names, and the mapping is defined once in the contract, so it is fully traceable.
# MAGIC - Each load is **appended**, never overwritten, so Raw keeps the full history of every file ever received.
# MAGIC
# MAGIC **Audit columns added to every row:**
# MAGIC
# MAGIC | Column | Meaning |
# MAGIC |---|---|
# MAGIC | `_load_id` | Unique ID of this load |
# MAGIC | `_loaded_at` | When it was loaded (UTC) |
# MAGIC | `_source_file` | File name as it arrived |
# MAGIC | `_file_sha256` | Fingerprint of the file content |
# MAGIC | `_contract_version` | Contract version the file was checked against |
# MAGIC | `_source_row_number` | Row position in the original file (1 = first data row) |
# MAGIC
# MAGIC **Row-count reconciliation:** before writing, the number of rows Spark parsed is compared with the number
# MAGIC of records counted independently by Python's CSV reader. If they differ (for example, a broken quote or a
# MAGIC description with an unexpected line break), the load is stopped and nothing is written.
# MAGIC
# MAGIC Each table also gets a `<table>_current` view that shows only the most recent load.

# COMMAND ----------

# MAGIC %pip install pyyaml --quiet

# COMMAND ----------

import csv
import fnmatch
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

CONFIG_PATH = os.environ.get("IFC_PIPELINE_CONFIG", "/Volumes/ifc_cfo/landing/files/config/pipeline_config.yml")

try:
    spark  # noqa: F821
    ON_DATABRICKS = True
except NameError:
    ON_DATABRICKS = False

AUDIT_COLUMNS = ["_load_id", "_loaded_at", "_source_file", "_file_sha256", "_contract_version", "_source_row_number"]

# COMMAND ----------

# MAGIC %md ## Helpers

# COMMAND ----------


def load_config(config_path: str) -> dict:
    config_path = Path(config_path).resolve()
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    contracts_dir = Path(cfg["environment"]["contracts_dir"])
    if not contracts_dir.is_absolute():
        contracts_dir = (config_path.parent / contracts_dir).resolve()
    cfg["_contracts_dir"] = contracts_dir
    return cfg


def load_contracts(contracts_dir: Path) -> dict:
    contracts = {}
    for path in sorted(contracts_dir.glob("*.yml")):
        with open(path) as f:
            c = yaml.safe_load(f)
        contracts[c["contract"]["name"]] = c
    return contracts


def load_order(contracts: dict) -> list:
    """Sources a contract depends on are loaded first (e.g. projects before monitoring)."""
    ordered, seen = [], set()

    def visit(name):
        if name in seen:
            return
        seen.add(name)
        dep = contracts[name]["contract"].get("depends_on")
        if dep and dep in contracts:
            visit(dep)
        ordered.append(name)

    for name in sorted(contracts):
        visit(name)
    return ordered


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def original_name(path: Path) -> str:
    """The gate prefixes files with a timestamp: 20261029T201713Z__name.csv -> name.csv"""
    return path.name.split("__", 1)[1] if "__" in path.name else path.name


def count_and_header(path: Path):
    """Independent count of data records using Python's CSV reader (handles quoted line breaks)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        n = 0
        try:
            for _ in reader:
                n += 1
        except csv.Error as e:
            raise ValueError(
                f"The file is not valid CSV after data row {n} (around file line {reader.line_num}). "
                f"Most likely an opening quote that is never closed. Parser said: {e}. Nothing was written."
            ) from None
    return header, n


def full_table_name(cfg: dict, short_name: str) -> str:
    return f"{cfg['environment']['catalog']}.{short_name}"


# COMMAND ----------

# MAGIC %md ## Databricks (Spark + Delta) implementation

# COMMAND ----------


def spark_already_loaded(table: str, sha: str) -> bool:
    if not spark.catalog.tableExists(table):  # noqa: F821
        return False
    return spark.sql(  # noqa: F821
        f"SELECT 1 FROM {table} WHERE _file_sha256 = '{sha}' LIMIT 1"
    ).count() > 0


def spark_load(path: Path, contract: dict, table: str, audit: dict, expected_rows: int) -> int:
    from pyspark.sql import functions as F
    from pyspark.sql.window import Window

    df = (
        spark.read  # noqa: F821
        .option("header", True)
        .option("multiLine", True)      # descriptions contain line breaks inside quotes
        .option("escape", '"')          # standard CSV: "" inside quotes is a literal quote
        .option("encoding", "UTF-8")
        .option("inferSchema", False)   # Raw keeps everything as text
        .csv(str(path))
    )

    # Row-count reconciliation before anything is written.
    parsed_rows = df.count()
    if parsed_rows != expected_rows:
        raise ValueError(
            f"Row count mismatch: Spark parsed {parsed_rows} rows, CSV reader counted {expected_rows}. "
            "The file may have a broken quote or line break. Nothing was written."
        )

    # Select by source name (column order doesn't matter) and rename to contract target names.
    df = df.select([F.col(f"`{c['source']}`").alias(c["target"]) for c in contract["schema"]])

    # Position of each row in the original file. A single-partition read preserves file order.
    df = df.withColumn("_mono", F.monotonically_increasing_id())
    df = df.withColumn("_source_row_number", F.row_number().over(Window.orderBy("_mono"))).drop("_mono")

    for k in ["_load_id", "_source_file", "_file_sha256", "_contract_version"]:
        df = df.withColumn(k, F.lit(audit[k]))
    df = df.withColumn("_loaded_at", F.lit(audit["_loaded_at"]).cast("timestamp"))

    df.write.mode("append").saveAsTable(table)

    spark.sql(f"""
        CREATE OR REPLACE VIEW {table}_current
        COMMENT 'Most recent load of {table}. Use this for current-state analysis.'
        AS SELECT * FROM {table}
        WHERE _loaded_at = (SELECT MAX(_loaded_at) FROM {table})
    """)
    return parsed_rows


# COMMAND ----------

# MAGIC %md ## Local implementation (pandas) — used only for testing outside Databricks

# COMMAND ----------


def local_table_path(cfg: dict, table: str) -> Path:
    return Path(cfg["environment"]["landing_root"]) / "_local_tables" / f"{table}.csv"


def local_already_loaded(cfg: dict, table: str, sha: str) -> bool:
    import pandas as pd

    p = local_table_path(cfg, table)
    return p.exists() and sha in set(pd.read_csv(p, dtype=str, usecols=["_file_sha256"])["_file_sha256"])


def local_load(cfg: dict, path: Path, contract: dict, table: str, audit: dict, expected_rows: int) -> int:
    import pandas as pd

    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8-sig")
    if len(df) != expected_rows:
        raise ValueError(f"Row count mismatch: parsed {len(df)}, CSV reader counted {expected_rows}.")
    df = df[[c["source"] for c in contract["schema"]]]
    df.columns = [c["target"] for c in contract["schema"]]
    df["_source_row_number"] = range(1, len(df) + 1)
    for k, v in audit.items():
        df[k] = v
    out = local_table_path(cfg, table)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, mode="a", header=not out.exists(), index=False)
    return len(df)


# COMMAND ----------

# MAGIC %md ## Load log

# COMMAND ----------

LOG_FIELDS = ["load_id", "loaded_at", "source", "source_file", "file_sha256", "contract_version",
              "target_table", "status", "rows_loaded", "message", "moved_to"]


def write_load_log(cfg: dict, records: list):
    if not records:
        return
    if ON_DATABRICKS:
        from pyspark.sql.types import IntegerType, StringType, StructField, StructType

        schema = StructType([StructField(f, IntegerType() if f == "rows_loaded" else StringType())
                             for f in LOG_FIELDS])
        env = cfg["environment"]
        table = f"{env['catalog']}.{env['ops_schema']}.raw_load_log"
        spark.createDataFrame([[r[f] for f in LOG_FIELDS] for r in records], schema) \
            .write.mode("append").saveAsTable(table)  # noqa: F821
    else:
        p = Path(cfg["environment"]["landing_root"]) / "_raw_load_log.jsonl"
        with open(p, "a") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")


# COMMAND ----------

# MAGIC %md ## Run

# COMMAND ----------


def run_load_raw(config_path: str = CONFIG_PATH) -> list:
    cfg = load_config(config_path)
    contracts = load_contracts(cfg["_contracts_dir"])
    root = Path(cfg["environment"]["landing_root"])
    lz = cfg["landing_zone"]
    records = []

    for source in load_order(contracts):
        contract = contracts[source]
        table = full_table_name(cfg, contract["targets"]["raw"])
        src_dir = root / lz["accepted"] / source
        if not src_dir.exists():
            continue

        for path in sorted(p for p in src_dir.iterdir() if p.is_file() and not p.name.startswith(".")):
            now = datetime.now(timezone.utc)
            audit = {
                "_load_id": str(uuid.uuid4()),
                "_loaded_at": now.isoformat(),
                "_source_file": original_name(path),
                "_file_sha256": file_sha256(path),
                "_contract_version": str(contract["contract"]["version"]),
            }
            rec = {"load_id": audit["_load_id"], "loaded_at": audit["_loaded_at"], "source": source,
                   "source_file": audit["_source_file"], "file_sha256": audit["_file_sha256"],
                   "contract_version": audit["_contract_version"], "target_table": table,
                   "status": None, "rows_loaded": 0, "message": "", "moved_to": None}

            already = (spark_already_loaded(table, audit["_file_sha256"]) if ON_DATABRICKS
                       else local_already_loaded(cfg, table, audit["_file_sha256"]))
            dest_dir = root / lz["loaded"] / source
            dest_dir.mkdir(parents=True, exist_ok=True)

            if already:
                rec["status"] = "SKIPPED"
                rec["message"] = "This file content is already in the Raw table."
                rec["moved_to"] = str(shutil.move(str(path), str(dest_dir / path.name)))
                records.append(rec)
                continue

            try:
                _, expected = count_and_header(path)
                rows = (spark_load(path, contract, table, audit, expected) if ON_DATABRICKS
                        else local_load(cfg, path, contract, table, audit, expected))
                rec["status"], rec["rows_loaded"] = "LOADED", rows
                rec["message"] = f"{rows} rows appended; row count reconciled."
                rec["moved_to"] = str(shutil.move(str(path), str(dest_dir / path.name)))
            except Exception as e:  # leave the file in accepted/ so it can be retried
                rec["status"], rec["message"] = "FAILED", f"{type(e).__name__}: {e}"
            records.append(rec)

    write_load_log(cfg, records)
    return records


def print_summary(records: list):
    if not records:
        print("No accepted files waiting to be loaded. Run the schema gate first.")
        return
    for r in records:
        print(f"[{r['status']}] {r['source_file']} -> {r['target_table']}  rows={r['rows_loaded']}")
        print(f"    - {r['message']}")


# COMMAND ----------

if __name__ == "__main__" or ON_DATABRICKS:
    results = run_load_raw()
    print_summary(results)
    failed = [r for r in results if r["status"] == "FAILED"]
    if failed:
        raise RuntimeError(f"Raw load failed for {len(failed)} file(s). See ops.raw_load_log. "
                           "Failed files were left in accepted/ for retry.")
