# Databricks notebook source
# MAGIC %md
# MAGIC # 00_config — shared configuration
# MAGIC
# MAGIC Every notebook in this solution starts with `%run ../00_setup/00_config` (or `../../00_setup/00_config` from `04_answers/wsN`).
# MAGIC Change names **only here**. Nothing else in the solution hard-codes a catalog, schema, endpoint or warehouse.
# MAGIC
# MAGIC | Setting | Purpose |
# MAGIC |---|---|
# MAGIC | `CATALOG`, `SCHEMA` | Unity Catalog location of every table, view and function |
# MAGIC | `VOLUME` | Unity Catalog volume holding the raw CSV files exactly as delivered |
# MAGIC | `LLM_ENDPOINT` | Foundation-model endpoint used for text extraction (`ai_query`) and by the agent |
# MAGIC | `SQL_WAREHOUSE_ID` | Warehouse the agent and the app use to run governed SQL |
# MAGIC | `GENIE_SPACE_ID` | Genie space built in `02_agent/02_agent_capabilities` |
# MAGIC | `ECL_LOSS_RATE` | Simplified expected-credit-loss assumption from the case brief (60% of disbursed on Past Due) |

# COMMAND ----------

# ---- Unity Catalog location -------------------------------------------------
CATALOG = "workspace"          # in the shared competition workspace use the catalog you were given
SCHEMA = "cfo_copilot"
VOLUME = "raw_files"

RAW_DIR = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"
PROJECTS_FILE = f"{RAW_DIR}/synthetic_ifc_projects_5000.csv"
MONITORING_FILE = f"{RAW_DIR}/synthetic_project_monitoring.csv"

# ---- AI components ----------------------------------------------------------
# Any chat model served under "Serving" works. Check the exact name in your workspace.
LLM_ENDPOINT = "databricks-meta-llama-3-3-70b-instruct"
RUN_LLM_EXTRACTION = True          # False = rule-based text features only (no model calls)
LLM_EXTRACTION_LIMIT = None        # e.g. 5 for a first smoke test; None = every new or changed description
LLM_BATCH_SIZE = 250               # rows per committed batch (progress is saved after each batch)
LLM_PARALLELISM = 32               # parallel model calls; the first full run at 16 had 0 rate-limit errors
# Measured on the trial pay-per-token Llama 3.3 70B endpoint: ~5,000 descriptions took ~60 min at 16 parallel calls.
# Re-runs only send new, changed or failed descriptions, so the full cost is paid once.

SQL_WAREHOUSE_ID = "a7792da7c24287a3"  # Serverless Starter Warehouse (SQL Warehouses -> warehouse -> URL / Connection details)
GENIE_SPACE_ID = "01f1dfb2b45c126bb81182a497d5866f"  # from the Genie space URL: .../genie/rooms/<GENIE_SPACE_ID>
UC_MODEL_NAME = f"{CATALOG}.{SCHEMA}.cfo_decision_advisor"

# ---- Business parameters (also recorded in ref_assumptions) -----------------
ECL_LOSS_RATE = 0.60               # case brief: Past Due = default, 60% of disbursed is lost
ALLOCATION_TOLERANCE_MUSD = 1.0    # Q28: Board total vs product allocations

def T(name: str) -> str:
    """Fully-qualified Unity Catalog name for an object in this solution."""
    return f"{CATALOG}.{SCHEMA}.{name}"

# COMMAND ----------

# Create the containers if they do not exist yet. In a shared workspace the
# catalog usually exists already and you may lack CREATE CATALOG - that is fine.
try:
    spark.sql(f"CREATE CATALOG IF NOT EXISTS {CATALOG}")
except Exception as e:
    print(f"Skipping CREATE CATALOG ({type(e).__name__}); using existing catalog {CATALOG}")

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA} COMMENT 'IFC CFO Office portfolio intelligence (Forward Deployed challenge)'")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.{VOLUME} COMMENT 'Raw source files exactly as delivered by IFC'")
spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# Session variable so %sql cells use the same loss rate as Python (referenced as ecl_loss_rate).
spark.sql(f"DECLARE OR REPLACE VARIABLE ecl_loss_rate DOUBLE DEFAULT {ECL_LOSS_RATE}")

# COMMAND ----------

# ---- Answer register ---------------------------------------------------------
# Every WS1/WS2 answer is produced through `answer(...)`, which runs the SQL,
# displays the result and records question, SQL, assumptions and a result
# preview. `persist_answers(...)` writes them to the `answers_register` table, so each
# figure stays traceable to its exact query (a requirement in the case brief).
import json
from datetime import datetime, timezone

_ANSWERS = []

def answer(question_id: str, question: str, sql: str, assumptions: str = "", show: bool = True):
    df = spark.sql(sql)
    pdf = df.limit(500).toPandas()
    _ANSWERS.append({
        "question_id": question_id,
        "question": question,
        "sql_text": sql.strip(),
        "assumptions": assumptions.strip(),
        "row_count": int(df.count()),
        "result_preview_json": pdf.to_json(orient="records", date_format="iso"),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    })
    if show:
        print(f"{question_id}: {question}")
        if assumptions:
            print(f"  Assumptions: {assumptions}")
        display(df)
    return df

def persist_answers(workstream: str):
    if not _ANSWERS:
        print("No answers recorded")
        return
    rows = [dict(a, workstream=workstream) for a in _ANSWERS]
    sdf = spark.createDataFrame(rows).select(
        "workstream", "question_id", "question", "sql_text", "assumptions",
        "row_count", "result_preview_json", "computed_at")
    spark.sql("""
        CREATE TABLE IF NOT EXISTS answers_register (
          workstream STRING, question_id STRING, question STRING, sql_text STRING,
          assumptions STRING, row_count BIGINT, result_preview_json STRING, computed_at STRING)
        COMMENT 'Every answer submitted for WS1/WS2/WS3 with the SQL and assumptions used to produce it'
    """)
    spark.sql(f"DELETE FROM answers_register WHERE workstream = '{workstream}'")
    sdf.write.mode("append").saveAsTable("answers_register")
    print(f"Saved {len(rows)} answers for {workstream} to {T('answers_register')}")
    _ANSWERS.clear()

print(f"Config loaded: {CATALOG}.{SCHEMA} | raw files in {RAW_DIR} | LLM {LLM_ENDPOINT}")
