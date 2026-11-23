# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Load and prepare
# MAGIC
# MAGIC Runs the whole data pipeline, from a delivered file to the certified tables the app and the agents read.
# MAGIC Each stage is its own notebook in this folder, so it can be read, tested and rerun on its own. This notebook runs
# MAGIC them in order and stops at the first failure.
# MAGIC
# MAGIC | # | Notebook | What it does |
# MAGIC |---|---|---|
# MAGIC | 1 | `01_schema_gate` | Checks each new file's header against its data contract (`00_setup/contracts/`). An added, removed or renamed column, an empty file or an unknown file name **stops the run on purpose**: the file is moved to `held/` and the job's failure email alerts the data owner. |
# MAGIC | 2 | `02_load_raw` | Loads every value as text into `raw_*`, with audit columns. History is kept; row counts are reconciled before writing. |
# MAGIC | 3 | `03_validate` | Types and business rules from the contracts: unusable rows are quarantined, the rest are flagged with a severity and an owner. Stops without replacing tables if more than 5% would be quarantined. |
# MAGIC | 4 | `00_reference` | Business definitions A01–A24 (`ref_assumptions`), region mapping, vocabularies, market research. |
# MAGIC | 5 | `04_enrich` | Reads the free-text project descriptions with an LLM (`ai_query`) into fields: capacity, product, new renewable generation. Uncertain readings go to a reviewer. |
# MAGIC | 6 | `05_certify` | `certified_investment_portfolio`: one governed row per project, every column commented. |
# MAGIC | 7 | `06_dq_checks` | 72 checks (raw = validated + quarantined = certified, keys, allowed values, flag counts) and the open issues per owner (`ops_dq_issues`). |
# MAGIC | 8 | `07_client_views` | Client scorecard and early-warning tables used by the app. |
# MAGIC
# MAGIC Then run `04_answers/ws1`, `ws2` and `ws3`. The scheduled job `cloudstruck_full_pipeline` runs the same notebooks
# MAGIC as separate tasks. Settings: `00_setup/config/pipeline_config.yml`.

# COMMAND ----------

dbutils.widgets.text("config_path", "", "Config path (blank = 00_setup/config/pipeline_config.yml)")  # noqa: F821
dbutils.widgets.text("start_at", "", "Start at notebook (blank = from the start)")  # noqa: F821
CONFIG_PATH = dbutils.widgets.get("config_path").strip()  # noqa: F821
START_AT = dbutils.widgets.get("start_at").strip()  # noqa: F821

STAGES = ["01_schema_gate", "02_load_raw", "03_validate", "00_reference", "04_enrich", "05_certify", "06_dq_checks",
          "07_client_views"]
TIMEOUT_SECONDS = 2 * 60 * 60  # the LLM extraction in 04_enrich is the slowest stage (about 16 minutes on 5,000 rows)

# COMMAND ----------

import time  # noqa: E402

if START_AT and START_AT not in STAGES:
    raise ValueError(f"start_at must be one of {STAGES}")
todo = STAGES[STAGES.index(START_AT):] if START_AT else STAGES
args = {"config_path": CONFIG_PATH} if CONFIG_PATH else {}
for i, nb in enumerate(todo, 1):
    t0 = time.time()
    print(f"[{i}/{len(todo)}] {nb} ...", flush=True)
    try:
        out = dbutils.notebook.run(f"./{nb}", TIMEOUT_SECONDS, args)  # noqa: F821
    except Exception as e:
        print(f"Stopped at {nb}. Open the failed run above for details; fix it, then rerun with start_at = {nb}.")
        raise
    print(f"      done in {time.time() - t0:,.0f} s{f' · {out}' if out else ''}")
print("Pipeline complete: the certified tables are ready. Next: 04_answers/ws1, ws2, ws3.")
