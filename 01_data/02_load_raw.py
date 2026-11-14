# Databricks notebook source
# MAGIC %md
# MAGIC # Stage 2 — Load Raw
# MAGIC
# MAGIC Loads every file the schema gate accepted into a **Raw** Delta table, one table per source
# MAGIC (`raw_projects`, `raw_monitoring`).
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
# MAGIC | `_reporting_month` | Reporting month (first day), from the landing folder `incoming/YYYY-MM/` |
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
# MAGIC **Months and re-uploads.** Every load is registered in `ops_monthly_loads` with its reporting month. Per month and
# MAGIC source exactly one load is **active**: the newest. A corrected October file therefore supersedes the earlier
# MAGIC October load (still in Raw, marked superseded) without touching any other month.
# MAGIC
# MAGIC `<table>_current` shows the active load of the **latest complete month** (the highest month with an active load for
# MAGIC every source), not simply the most recent upload, so back-filling an old month never changes what is current.
# MAGIC `<table>_active` shows the active load of every month.

# COMMAND ----------

# MAGIC %pip install pyyaml --quiet

# COMMAND ----------

import csv
import fnmatch
import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone

# ---- Find the repo root and import the shared helpers (same cell in every pipeline notebook) ----------
import os
import sys
from pathlib import Path


def _repo_root():
    """Folder holding config/ and 00_setup/. Tries this file, the working directory, then the notebook path."""
    starts = []
    if "__file__" in globals():
        starts.append(Path(__file__).resolve().parent)
    starts.append(Path(os.getcwd()))
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # noqa: F821
        starts.append(Path(nb if nb.startswith("/Workspace") else "/Workspace" + nb).parent)
    except Exception:
        pass
    for start in starts:
        for folder in [start, *start.parents]:
            if (folder / "00_setup" / "ifc_common.py").is_file():
                return folder
    raise FileNotFoundError("Could not find the repo root (the folder that holds 00_setup/ifc_common.py). "
                            f"Tried: {[str(s) for s in starts]}")


def _mirror_repo():
    """Serverless workaround: some workspaces cannot read workspace files next to the running notebook
    (OSError [Errno 5]). Copy the repo's code, config, contracts and data to local disk through the Workspace API."""
    import base64
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.workspace import ExportFormat, ObjectType
    nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # noqa: F821
    ws_root = nb[len("/Workspace"):] if nb.startswith("/Workspace/") else nb
    ws_root = ws_root.rsplit("/", 2)[0]          # notebooks sit one folder below the repo root
    local = Path("/tmp/ifc_repo_mirror")
    w = WorkspaceClient()
    for sub in ["00_setup", "config", "contracts", "data"]:
        for obj in w.workspace.list(f"{ws_root}/{sub}", recursive=True):
            if obj.object_type != ObjectType.FILE or obj.path.lower().endswith((".pdf", ".xlsx")):
                continue
            dest = local / obj.path[len(ws_root) + 1:]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(base64.b64decode(w.workspace.export(obj.path, format=ExportFormat.AUTO).content))
    os.environ["IFC_WS_REPO_ROOT"] = "/Workspace" + ws_root
    print(f"Workspace files not readable here; using a copy of {ws_root} at {local}")
    return local


def _readable_repo_root():
    try:
        root = _repo_root()
        with open(root / "00_setup" / "ifc_common.py") as f:
            f.read(1)
        return root
    except OSError:
        return _mirror_repo()


def _local_path(p):
    """Map a /Workspace path inside the repo to the local copy (no-op when the repo is read in place)."""
    ws = os.environ.get("IFC_WS_REPO_ROOT")
    if p and ws and str(p).startswith(ws):
        return str(REPO_ROOT) + str(p)[len(ws):]
    return p


REPO_ROOT = _readable_repo_root()
if str(REPO_ROOT / "00_setup") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "00_setup"))
try:
    import ifc_common  # noqa: E402,F401
except OSError:
    # On serverless, reading a workspace file sometimes fails with "[Errno 5] Input/output error" for the whole run.
    # The Workspace API still serves it, so load the helper module from there.
    import types
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.workspace import ExportFormat
    _helper = str(REPO_ROOT / "00_setup" / "ifc_common.py")
    ifc_common = types.ModuleType("ifc_common")
    ifc_common.__file__ = _helper
    exec(compile(WorkspaceClient().workspace.download(_helper, format=ExportFormat.AUTO).read().decode("utf-8"),  # noqa: S102
                 _helper, "exec"), ifc_common.__dict__)
    sys.modules["ifc_common"] = ifc_common
from ifc_common import T, load_config, load_contracts, load_order, resolve_config_path  # noqa: E402
from ifc_monthly import (active_sha, incomplete_months, latest_month, month_from_folder, month_label,  # noqa: E402
                         point_current_views, register_load)

try:
    dbutils.widgets.text("config_path", "", "Config path (blank = repo config)")  # noqa: F821
    _widget = dbutils.widgets.get("config_path")  # noqa: F821
except NameError:
    _widget = None
CONFIG_PATH = resolve_config_path(_local_path(_widget), REPO_ROOT)

try:
    spark  # noqa: F821
    ON_DATABRICKS = True
except NameError:
    ON_DATABRICKS = False

AUDIT_COLUMNS = ["_load_id", "_reporting_month", "_loaded_at", "_source_file", "_file_sha256", "_contract_version",
                 "_source_row_number"]

# COMMAND ----------

# MAGIC %md ## Helpers

# COMMAND ----------


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


# COMMAND ----------

# MAGIC %md ## Databricks (Spark + Delta) implementation

# COMMAND ----------


def spark_already_loaded(cfg: dict, month, source: str, sha: str) -> bool:
    """True if this exact content is already the active load for the month and source."""
    return active_sha(spark, cfg, month, source) == sha  # noqa: F821


def month_check(df, month) -> str:
    """Warn (never block) when the data's latest As of Date is not in the folder's month."""
    if "as_of_date" not in df.columns:
        return ""
    latest = df.selectExpr("max(try_cast(as_of_date AS DATE)) AS d").first()["d"]
    if latest is None or (latest.year, latest.month) == (month.year, month.month):
        return ""
    return (f"Warning: folder month is {month_label(month)} but the latest As of Date in the file is {latest}. "
            "Check that the file was put in the right month folder.")


def spark_load(path: Path, contract: dict, table: str, audit: dict, expected_rows: int):
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
    df = df.withColumn("_reporting_month", F.lit(audit["_reporting_month"]).cast("date"))
    df = df.withColumn("_loaded_at", F.lit(audit["_loaded_at"]).cast("timestamp"))

    message = month_check(df, audit["_month"])
    # mergeSchema: a Raw table created before monthly folders existed gets the _reporting_month column added.
    df.write.mode("append").option("mergeSchema", "true").saveAsTable(table)
    return parsed_rows, message


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
        if not k.startswith("_month"):
            df[k] = v
    out = local_table_path(cfg, table)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, mode="a", header=not out.exists(), index=False)
    return len(df), ""


# COMMAND ----------

# MAGIC %md ## Load log

# COMMAND ----------

LOG_FIELDS = ["load_id", "loaded_at", "reporting_month", "source", "source_file", "file_sha256", "contract_version",
              "target_table", "status", "rows_loaded", "message", "moved_to"]


def write_load_log(cfg: dict, records: list):
    if not records:
        return
    if ON_DATABRICKS:
        from pyspark.sql.types import IntegerType, StringType, StructField, StructType

        schema = StructType([StructField(f, IntegerType() if f == "rows_loaded" else StringType())
                             for f in LOG_FIELDS])
        table = T(cfg, "ops_raw_load_log")
        spark.createDataFrame([[r[f] for f in LOG_FIELDS] for r in records], schema) \
            .write.mode("append").option("mergeSchema", "true").saveAsTable(table)  # noqa: F821
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

    accepted = root / lz["accepted"]
    month_dirs = sorted(d for d in accepted.iterdir() if d.is_dir() and month_from_folder(d.name)) \
        if accepted.exists() else []

    # Months oldest first; within a month, projects before monitoring; within a source, files in arrival order
    # (the gate prefixes a timestamp), so the newest upload of a month is loaded last and ends up active.
    for month_dir in month_dirs:
        month = month_from_folder(month_dir.name)
        for source in load_order(contracts):
            contract = contracts[source]
            table = T(cfg, contract["targets"]["raw"])
            src_dir = month_dir / source
            if not src_dir.exists():
                continue

            for path in sorted(p for p in src_dir.iterdir() if p.is_file() and not p.name.startswith(".")):
                now = datetime.now(timezone.utc)
                audit = {
                    "_load_id": str(uuid.uuid4()),
                    "_reporting_month": month.isoformat(),
                    "_loaded_at": now.isoformat(),
                    "_source_file": original_name(path),
                    "_file_sha256": file_sha256(path),
                    "_contract_version": str(contract["contract"]["version"]),
                    "_month": month,
                }
                rec = {"load_id": audit["_load_id"], "loaded_at": audit["_loaded_at"],
                       "reporting_month": month_label(month), "source": source,
                       "source_file": audit["_source_file"], "file_sha256": audit["_file_sha256"],
                       "contract_version": audit["_contract_version"], "target_table": table,
                       "status": None, "rows_loaded": 0, "message": "", "moved_to": None}

                already = (spark_already_loaded(cfg, month, source, audit["_file_sha256"]) if ON_DATABRICKS
                           else local_already_loaded(cfg, table, audit["_file_sha256"]))
                dest_dir = root / lz["loaded"] / month_dir.name / source
                dest_dir.mkdir(parents=True, exist_ok=True)

                if already:
                    rec["status"] = "SKIPPED"
                    rec["message"] = f"Identical to the active {source} load for {month_label(month)}."
                    rec["moved_to"] = str(shutil.move(str(path), str(dest_dir / path.name)))
                    records.append(rec)
                    continue

                try:
                    _, expected = count_and_header(path)
                    rows, warning = (spark_load(path, contract, table, audit, expected) if ON_DATABRICKS
                                     else local_load(cfg, path, contract, table, audit, expected))
                    replaced = active_sha(spark, cfg, month, source) if ON_DATABRICKS else None  # noqa: F821
                    if ON_DATABRICKS:
                        register_load(spark, cfg, {  # noqa: F821
                            "load_id": audit["_load_id"], "reporting_month": month, "source": source,
                            "source_file": audit["_source_file"], "file_sha256": audit["_file_sha256"],
                            "rows_loaded": rows, "loaded_at": audit["_loaded_at"], "check_message": warning})
                    rec["status"], rec["rows_loaded"] = ("LOADED_WITH_WARNING" if warning else "LOADED"), rows
                    rec["message"] = (f"{rows} rows appended; row count reconciled. "
                                      + (f"Replaces the earlier {source} file for {month_label(month)} "
                                         "(kept in Raw, marked superseded). " if replaced else "")
                                      + warning).strip()
                    rec["moved_to"] = str(shutil.move(str(path), str(dest_dir / path.name)))
                except Exception as e:  # leave the file in accepted/ so it can be retried
                    rec["status"], rec["message"] = "FAILED", f"{type(e).__name__}: {e}"
                records.append(rec)

    # Files left in the old layout accepted/<source>/ (before month folders) cannot be given a month.
    for source in contracts:
        legacy = accepted / source
        if legacy.exists() and any(p.is_file() for p in legacy.iterdir()):
            print(f"Note: {legacy} holds files without a month. Move them to incoming/YYYY-MM/ and re-run the gate.")

    write_load_log(cfg, records)
    if ON_DATABRICKS:
        sources = load_order(contracts)
        latest = latest_month(spark, cfg, sources)  # noqa: F821
        for m, missing in incomplete_months(spark, cfg, sources).items():  # noqa: F821
            print(f"Month {month_label(m)} is incomplete (no {', '.join(missing)} file yet); it is not processed.")
        if latest:
            point_current_views(spark, cfg, contracts, latest)  # noqa: F821
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
        raise RuntimeError(f"Raw load failed for {len(failed)} file(s). See ops_raw_load_log. "
                           "Failed files were left in accepted/ for retry.")
