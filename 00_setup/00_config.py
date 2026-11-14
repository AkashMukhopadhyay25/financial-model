# Databricks notebook source
# MAGIC %md
# MAGIC # 00_config — shared configuration and setup
# MAGIC
# MAGIC **Run it once on its own** to create the schema, the landing volume and its folders. Every other notebook
# MAGIC either starts with `%run ../00_setup/00_config` (or `../../00_setup/00_config` from `04_answers/wsN`) or
# MAGIC imports `00_setup/ifc_common.py`.
# MAGIC
# MAGIC All values come from **`config/pipeline_config.yml`**. Nothing here or anywhere else hard-codes a catalog,
# MAGIC schema, threshold, endpoint or ID. To change a setting, edit the YAML and re-run.
# MAGIC
# MAGIC | Python name | From config | Purpose |
# MAGIC |---|---|---|
# MAGIC | `CATALOG`, `SCHEMA` | `environment` | Unity Catalog location of every table, view and function |
# MAGIC | `VOLUME`, `LANDING_ROOT` | `environment` | Landing volume `/Volumes/{catalog}/{schema}/{volume}` with `incoming/ accepted/ held/ loaded/` |
# MAGIC | `LLM_ENDPOINT`, `RUN_LLM_EXTRACTION`, `LLM_*` | `ai` | Model endpoint and text-extraction settings |
# MAGIC | `SQL_WAREHOUSE_ID`, `GENIE_SPACE_ID`, `UC_MODEL_NAME` | `serving` | Used by the agent and the app |
# MAGIC | `ECL_LOSS_RATE`, `Q28_ALLOCATION_THRESHOLD_MUSD`, `CLIENT_BANDS`, `HEALTH_WEIGHTS` | `business` | Business parameters (also in `ref_assumptions`) |
# MAGIC | `T("name")` | — | Fully-qualified name `{catalog}.{schema}.name` |
# MAGIC
# MAGIC The config file is found in this order: environment variable `IFC_PIPELINE_CONFIG` → the `config_path`
# MAGIC widget at the top of the notebook → `config/pipeline_config.yml` in the same repo folder as this notebook.
# MAGIC
# MAGIC PyYAML ships with Databricks runtimes. If you see `No module named 'yaml'`, run `%pip install pyyaml` first.

# COMMAND ----------

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
from ifc_common import T as _T, load_config, resolve_config_path  # noqa: E402

try:
    dbutils.widgets.text("config_path", "", "Config path (blank = repo config)")  # noqa: F821
    _widget = dbutils.widgets.get("config_path")  # noqa: F821
except NameError:
    _widget = None
CONFIG_PATH = resolve_config_path(_local_path(_widget), REPO_ROOT)
CFG = load_config(CONFIG_PATH)

# COMMAND ----------

# ---- Values from config/pipeline_config.yml -------------------------------------------------------------
_env, _ai, _srv, _biz = CFG["environment"], CFG["ai"], CFG["serving"], CFG["business"]

CATALOG = _env["catalog"]
SCHEMA = _env["schema"]
VOLUME = _env["volume"]
LANDING_ROOT = _env["landing_root"]
LANDING_FOLDERS = [CFG["landing_zone"][k] for k in ("incoming", "accepted", "held", "loaded")]

LLM_ENDPOINT = _ai["llm_endpoint"]
RUN_LLM_EXTRACTION = bool(_ai["run_llm_extraction"])
LLM_EXTRACTION_LIMIT = _ai.get("llm_extraction_limit")   # None = every new or changed description
LLM_BATCH_SIZE = int(_ai["llm_batch_size"])
LLM_PARALLELISM = int(_ai["llm_parallelism"])

SQL_WAREHOUSE_ID = _srv.get("sql_warehouse_id") or ""
GENIE_SPACE_ID = _srv.get("genie_space_id") or ""
UC_MODEL_NAME = _T(CFG, _srv["uc_model_name"])

ECL_LOSS_RATE = float(_biz["ecl_loss_rate"])
Q28_ALLOCATION_THRESHOLD_MUSD = float(_biz["q28_allocation_threshold_musd"])
ALLOCATION_TOLERANCE_MUSD = float(CFG["thresholds"]["amount_reconciliation_tolerance_musd"])  # row flags
CLIENT_BANDS = dict(_biz["client_bands"])
HEALTH_WEIGHTS = dict(_biz["health_score_weights"])


def T(name: str) -> str:
    """Fully-qualified Unity Catalog name for an object in this solution."""
    return _T(CFG, name)


# COMMAND ----------

# ---- Create the containers if they do not exist yet ------------------------------------------------------
# In a shared workspace the catalog usually exists already and you may lack CREATE CATALOG; that is fine.
try:
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
except Exception as e:
    print(f"Skipping CREATE CATALOG ({type(e).__name__}); using existing catalog {CATALOG}")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} "
          "COMMENT 'IFC CFO Office portfolio intelligence. Layers are name prefixes: raw_, validated_, enriched_, certified_, plus ref_ and ops_.'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} "
          "COMMENT 'Landing zone for source files: incoming/, accepted/, held/, loaded/'")
for _folder in LANDING_FOLDERS:
    os.makedirs(f"{LANDING_ROOT}/{_folder}", exist_ok=True)

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# Session variable so %sql cells use the same loss rate as Python (referenced as ecl_loss_rate).
# Needs serverless or DBR 14.1+. If it fails, write the config value directly into the SQL instead.
try:
    spark.sql(f"DECLARE OR REPLACE VARIABLE ecl_loss_rate DOUBLE DEFAULT {ECL_LOSS_RATE}")
except Exception as e:
    print(f"Could not declare SQL variable ecl_loss_rate ({type(e).__name__}): {e}")

# COMMAND ----------

# ---- Answer register ---------------------------------------------------------------------------------------
# Every WS1/WS2 answer is produced through `answer(...)`, which runs the SQL, displays the result and records
# the question, SQL, assumptions and a result preview. `persist_answers(...)` writes them to `answers_register`,
# so each figure stays traceable to its exact query (a requirement in the case brief).
#
# Sensitivity note (assumption A03): a question that names no status includes every status, Dropped included.
# For the questions this affects, pass `sensitivity_sql` (the same query excluding Dropped) and
# `sensitivity_label` (e.g. "Excluding Dropped"); both figures are stored side by side.
import json
from datetime import datetime, timezone

_ANSWERS = []

ANSWERS_REGISTER_COLUMNS = [
    ("workstream", "STRING"), ("question_id", "STRING"), ("question", "STRING"), ("sql_text", "STRING"),
    ("assumptions", "STRING"), ("assumption_ids", "STRING"), ("row_count", "BIGINT"),
    ("result_preview_json", "STRING"), ("sensitivity_label", "STRING"), ("sensitivity_sql", "STRING"),
    ("sensitivity_preview_json", "STRING"), ("scope_where", "STRING"), ("rows_in_scope", "BIGINT"),
    ("rows_needing_review", "BIGINT"), ("rows_high_severity", "BIGINT"), ("rows_text_review", "BIGINT"),
    ("computed_at", "STRING"),
]

# Table whose rows an answer's scope refers to (for the data-quality counts stored with every answer).
SCOPE_TABLE = "certified_investment_portfolio"


def answer(question_id: str, question: str, sql: str, assumptions: str = "", show: bool = True,
           assumption_ids: str = "", sensitivity_sql: str = None, sensitivity_label: str = None,
           scope_where: str = None):
    """Run one answer query, record it for the register, and display it.

    assumption_ids     comma list of ref_assumptions IDs, e.g. "A02,A03"
    sensitivity_sql    optional alternative query (e.g. the same query excluding Dropped)
    sensitivity_label  short label for it, e.g. "Excluding Dropped"
    scope_where        WHERE condition on certified_investment_portfolio selecting the projects the answer covers
                       ("TRUE" = all). Used to count, deterministically, how many of those projects carry open
                       data-quality issues; the counts are stored with the answer and shown as its caveat.
    """
    df = spark.sql(sql)
    scope = None
    if scope_where:
        scope = spark.sql(f"""
            SELECT count(*) AS n, count_if(needs_review) AS review, count_if(dq_max_severity = 'high') AS high,
                   count_if(text_attributes_need_review) AS text
            FROM {T(SCOPE_TABLE)} WHERE {scope_where}""").first()
    pdf = df.limit(500).toPandas()
    sens_json = None
    if sensitivity_sql:
        sens_df = spark.sql(sensitivity_sql)
        sens_json = sens_df.limit(500).toPandas().to_json(orient="records", date_format="iso")
    _ANSWERS.append({
        "question_id": question_id,
        "question": question,
        "sql_text": sql.strip(),
        "assumptions": assumptions.strip(),
        "assumption_ids": ",".join(a.strip() for a in assumption_ids.split(",") if a.strip()),
        "row_count": int(df.count()),
        "result_preview_json": pdf.to_json(orient="records", date_format="iso"),
        "sensitivity_label": (sensitivity_label or ("Sensitivity" if sensitivity_sql else None)),
        "sensitivity_sql": sensitivity_sql.strip() if sensitivity_sql else None,
        "sensitivity_preview_json": sens_json,
        "scope_where": scope_where.strip() if scope_where else None,
        "rows_in_scope": int(scope["n"]) if scope else None,
        "rows_needing_review": int(scope["review"]) if scope else None,
        "rows_high_severity": int(scope["high"]) if scope else None,
        "rows_text_review": int(scope["text"]) if scope else None,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    })
    if show:
        print(f"{question_id}: {question}")
        if assumptions:
            print(f"  Assumptions: {assumptions}")
        if assumption_ids:
            print(f"  Assumption IDs: {assumption_ids}")
        if scope:
            print(f"  Data quality: {scope['review']} of {scope['n']} projects in scope have open data-quality issues "
                  f"({scope['high']} high severity); {scope['text']} have text attributes awaiting review.")
        display(df)  # noqa: F821
        if sensitivity_sql:
            print(f"  Sensitivity: {sensitivity_label or 'Sensitivity'}")
            display(spark.sql(sensitivity_sql))  # noqa: F821
    return df


def _ensure_answers_register():
    """Create answers_register, or add any new columns to an existing one (existing rows are kept)."""
    table = T("answers_register")
    if not spark.catalog.tableExists(table):
        cols = ", ".join(f"{c} {t}" for c, t in ANSWERS_REGISTER_COLUMNS)
        spark.sql(f"CREATE TABLE {table} ({cols}) "
                  "COMMENT 'Every answer submitted for WS1/WS2/WS3 with the SQL, assumptions and sensitivity figures used to produce it'")
        return
    existing = {f.name.lower() for f in spark.table(table).schema.fields}
    missing = [(c, t) for c, t in ANSWERS_REGISTER_COLUMNS if c not in existing]
    if missing:
        spark.sql(f"ALTER TABLE {table} ADD COLUMNS (" + ", ".join(f"{c} {t}" for c, t in missing) + ")")
        print(f"answers_register: added columns {[c for c, _ in missing]}")


def persist_answers(workstream: str):
    """Replace this workstream's rows in answers_register with the answers recorded in this run."""
    if not _ANSWERS:
        print("No answers recorded")
        return
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    _ensure_answers_register()
    schema = StructType([StructField(c, LongType() if t == "BIGINT" else StringType())
                         for c, t in ANSWERS_REGISTER_COLUMNS])
    rows = [[dict(a, workstream=workstream).get(c) for c, _ in ANSWERS_REGISTER_COLUMNS] for a in _ANSWERS]
    sdf = spark.createDataFrame(rows, schema)
    spark.sql(f"DELETE FROM {T('answers_register')} WHERE workstream = '{workstream}'")
    sdf.write.mode("append").saveAsTable(T("answers_register"))
    print(f"Saved {len(rows)} answers for {workstream} to {T('answers_register')}")
    _ANSWERS.clear()


print(f"Config loaded from {CONFIG_PATH}")
print(f"  location {CATALOG}.{SCHEMA} | landing {LANDING_ROOT} | LLM {LLM_ENDPOINT}")
