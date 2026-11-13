# Databricks notebook source
# MAGIC %md
# MAGIC # Stage 1 — Schema Gate
# MAGIC
# MAGIC Every file dropped into the landing zone is checked against its **data contract**
# MAGIC before anything else happens.
# MAGIC
# MAGIC | Outcome | What happens |
# MAGIC |---|---|
# MAGIC | **PASSED** | Header matches the contract. File moves to `accepted/<source>/` for the Raw stage. |
# MAGIC | **PASSED_WITH_WARNINGS** | Only harmless differences (e.g. column order, if allowed in config). File moves on; warning is logged. |
# MAGIC | **HELD** | Column added, removed, renamed, duplicated, empty file, or no matching contract. File moves to `held/`, nothing downstream changes, the job fails so the developer is alerted. |
# MAGIC | **SKIPPED** | Exact same file content was already processed. |
# MAGIC
# MAGIC Downstream tables are never touched by a held file, so Genie and the app keep serving the last good data.
# MAGIC Every decision is written to the `ops_schema_gate_log` table.
# MAGIC
# MAGIC **To fix a held file:** either correct the file and drop it back into `incoming/`,
# MAGIC or (if the change is intended) update the contract, bump its `version`, and re-run.

# COMMAND ----------

# MAGIC %pip install pyyaml --quiet

# COMMAND ----------

import csv
import difflib
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


REPO_ROOT = _repo_root()
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

try:
    dbutils.widgets.text("config_path", "", "Config path (blank = repo config)")  # noqa: F821
    _widget = dbutils.widgets.get("config_path")  # noqa: F821
except NameError:
    _widget = None
CONFIG_PATH = resolve_config_path(_widget, REPO_ROOT)

try:  # running on Databricks
    spark  # noqa: F821  (provided by the Databricks runtime)
    ON_DATABRICKS = True
except NameError:
    ON_DATABRICKS = False

# COMMAND ----------

# MAGIC %md ## Header check

# COMMAND ----------


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def match_contract(file_name: str, contracts: list):
    matches = [c for c in contracts if fnmatch.fnmatch(file_name, c["contract"]["file_pattern"])]
    return matches


def read_header(path: Path):
    """Return (header, has_data_row, error). Handles UTF-8 BOM and quoted multi-line fields."""
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return None, False, "File is empty (no header row)."
            first_row = next(reader, None)
            return header, first_row is not None, None
    except UnicodeDecodeError as e:
        return None, False, f"File is not valid UTF-8: {e}"


def check_header(header: list, contract: dict, gate_cfg: dict) -> dict:
    expected = [col["source"] for col in contract["schema"]]
    received = header

    errors, warnings = [], []

    dupes = sorted({c for c in received if received.count(c) > 1})
    if dupes:
        errors.append(f"Duplicate column names: {dupes}")

    exp_set, rec_set = set(expected), set(received)
    missing = [c for c in expected if c not in rec_set]
    unexpected = [c for c in received if c not in exp_set]

    # Diagnose likely renames so the developer sees *why* a column is missing.
    probable_renames = []
    threshold = gate_cfg.get("rename_similarity_threshold", 0.6)
    remaining_unexpected = list(unexpected)
    for m in missing:
        best, best_score = None, 0.0
        for u in remaining_unexpected:
            if m.strip().lower() == u.strip().lower():
                score = 1.0
            else:
                score = difflib.SequenceMatcher(None, m.lower(), u.lower()).ratio()
            if score > best_score:
                best, best_score = u, score
        if best is not None and best_score >= threshold:
            note = " (differs only in case/whitespace)" if best_score == 1.0 else ""
            probable_renames.append(f"'{m}' -> '{best}'{note}")
            remaining_unexpected.remove(best)

    if missing:
        errors.append(f"Missing columns ({len(missing)}): {missing}")
    if unexpected:
        errors.append(f"Unexpected columns ({len(unexpected)}): {unexpected}")
    if probable_renames:
        errors.append(f"Probable renames: {probable_renames}")

    reordered = not missing and not unexpected and not dupes and received != expected
    if reordered:
        msg = "Columns are in a different order than the contract."
        if gate_cfg.get("allow_column_reorder", True):
            warnings.append(msg + " Allowed by config (columns are read by name).")
        else:
            errors.append(msg + " Not allowed by config.")

    return {
        "expected_columns": len(expected),
        "received_columns": len(received),
        "missing": missing,
        "unexpected": unexpected,
        "probable_renames": probable_renames,
        "reordered": reordered,
        "errors": errors,
        "warnings": warnings,
    }


# COMMAND ----------

# MAGIC %md ## Gate log (Delta table on Databricks, JSON-lines file when run locally)

# COMMAND ----------

LOG_COLUMNS = [
    "run_id", "checked_at", "file_name", "file_sha256", "source", "contract_version",
    "status", "expected_columns", "received_columns", "missing", "unexpected",
    "probable_renames", "messages", "moved_to",
]


def log_table_name(cfg) -> str:
    return T(cfg, "ops_schema_gate_log")


def local_log_path(cfg) -> Path:
    return Path(cfg["environment"]["landing_root"]) / "_schema_gate_log.jsonl"


def previously_processed_hashes(cfg) -> set:
    if ON_DATABRICKS:
        table = log_table_name(cfg)
        if not spark.catalog.tableExists(table):  # noqa: F821
            return set()
        rows = spark.sql(  # noqa: F821
            f"SELECT DISTINCT file_sha256 FROM {table} WHERE status IN ('PASSED', 'PASSED_WITH_WARNINGS')"
        ).collect()
        return {r.file_sha256 for r in rows}
    path = local_log_path(cfg)
    if not path.exists():
        return set()
    hashes = set()
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if rec["status"] in ("PASSED", "PASSED_WITH_WARNINGS"):
                hashes.add(rec["file_sha256"])
    return hashes


def write_log(cfg, records: list):
    if not records:
        return
    if ON_DATABRICKS:
        from pyspark.sql.types import ArrayType, IntegerType, StringType, StructField, StructType

        schema = StructType([
            StructField("run_id", StringType()), StructField("checked_at", StringType()),
            StructField("file_name", StringType()), StructField("file_sha256", StringType()),
            StructField("source", StringType()), StructField("contract_version", StringType()),
            StructField("status", StringType()), StructField("expected_columns", IntegerType()),
            StructField("received_columns", IntegerType()),
            StructField("missing", ArrayType(StringType())),
            StructField("unexpected", ArrayType(StringType())),
            StructField("probable_renames", ArrayType(StringType())),
            StructField("messages", ArrayType(StringType())), StructField("moved_to", StringType()),
        ])
        df = spark.createDataFrame([[r[c] for c in LOG_COLUMNS] for r in records], schema)  # noqa: F821
        df.write.mode("append").saveAsTable(log_table_name(cfg))
    else:
        path = local_log_path(cfg)
        with open(path, "a") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")


# COMMAND ----------

# MAGIC %md ## Run the gate

# COMMAND ----------


def move_file(src: Path, dest_dir: Path, run_ts: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{run_ts}__{src.name}"
    shutil.move(str(src), str(dest))
    return dest


def run_schema_gate(config_path: str = CONFIG_PATH) -> list:
    cfg = load_config(config_path)
    contracts = list(load_contracts(cfg["_contracts_dir"]).values())
    gate_cfg = cfg.get("schema_gate", {})
    lz = cfg["landing_zone"]
    root = Path(cfg["environment"]["landing_root"])
    incoming = root / lz["incoming"]
    incoming.mkdir(parents=True, exist_ok=True)

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    run_ts = now.strftime("%Y%m%dT%H%M%SZ")
    seen = previously_processed_hashes(cfg) if gate_cfg.get("skip_already_processed", True) else set()

    files = sorted(p for p in incoming.iterdir() if p.is_file() and not p.name.startswith("."))
    records = []

    for path in files:
        rec = {c: None for c in LOG_COLUMNS}
        rec.update(run_id=run_id, checked_at=now.isoformat(), file_name=path.name,
                   missing=[], unexpected=[], probable_renames=[], messages=[])
        rec["file_sha256"] = file_sha256(path)

        matches = match_contract(path.name, contracts)
        if len(matches) != 1:
            rec["status"] = "HELD"
            rec["messages"] = [
                "No contract matches this file name." if not matches
                else f"File name matches several contracts: {[m['contract']['name'] for m in matches]}"
            ]
            rec["moved_to"] = str(move_file(path, root / lz["held"], run_ts))
            records.append(rec)
            continue

        contract = matches[0]
        rec["source"] = contract["contract"]["name"]
        rec["contract_version"] = str(contract["contract"]["version"])

        if rec["file_sha256"] in seen:
            rec["status"] = "SKIPPED"
            rec["messages"] = ["Identical file content already accepted in an earlier run."]
            rec["moved_to"] = str(move_file(path, root / lz["held"] / "duplicates", run_ts))
            records.append(rec)
            continue

        header, has_data, read_error = read_header(path)
        if read_error or not has_data:
            rec["status"] = "HELD"
            rec["messages"] = [read_error or "File has a header but no data rows."]
            rec["moved_to"] = str(move_file(path, root / lz["held"], run_ts))
            records.append(rec)
            continue

        result = check_header(header, contract, gate_cfg)
        rec.update(expected_columns=result["expected_columns"], received_columns=result["received_columns"],
                   missing=result["missing"], unexpected=result["unexpected"],
                   probable_renames=result["probable_renames"],
                   messages=result["errors"] + result["warnings"])

        if result["errors"]:
            rec["status"] = "HELD"
            rec["moved_to"] = str(move_file(path, root / lz["held"], run_ts))
        else:
            rec["status"] = "PASSED_WITH_WARNINGS" if result["warnings"] else "PASSED"
            rec["moved_to"] = str(move_file(path, root / lz["accepted"] / rec["source"], run_ts))
            seen.add(rec["file_sha256"])
        records.append(rec)

    write_log(cfg, records)
    return records


def print_summary(records: list):
    if not records:
        print("No files in incoming/. Nothing to do.")
        return
    for r in records:
        print(f"[{r['status']}] {r['file_name']}  (source: {r['source']}, contract v{r['contract_version']})")
        for m in r["messages"]:
            print(f"    - {m}")
        print(f"    -> {r['moved_to']}")


# COMMAND ----------

if __name__ == "__main__" or ON_DATABRICKS:
    results = run_schema_gate()
    print_summary(results)
    held = [r for r in results if r["status"] == "HELD"]
    if held:
        # Fail the job on purpose so Databricks sends its failure alert.
        # All files were still processed and logged before this point.
        raise RuntimeError(
            f"Schema gate held {len(held)} file(s): {[r['file_name'] for r in held]}. "
            "See ops_schema_gate_log for details. Downstream tables were not changed."
        )
