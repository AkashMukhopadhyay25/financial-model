# Databricks notebook source
# MAGIC %md
# MAGIC # run_monthly_pipeline — one click: new uploads → monthly history → trends
# MAGIC
# MAGIC **To add data:** put the month's files in the landing volume under `incoming/YYYY-MM/`
# MAGIC (Catalog → `workspace` → your schema → Volumes → `landing` → `incoming` → create folder `2026-10` → Upload).
# MAGIC Then run this notebook (**Run all**). To correct a month, upload the corrected file into the same month folder and
# MAGIC run again: that month is replaced, every other month stays as it was.
# MAGIC
# MAGIC What it does:
# MAGIC 1. `01_schema_gate`: checks every new file (month folder required). Held files are reported at the end; they never
# MAGIC    stop good files from other months.
# MAGIC 2. `02_load_raw`: appends accepted files to Raw and registers them in `ops_monthly_loads` (newest upload per month
# MAGIC    and source is active).
# MAGIC 3. Works out which months changed: a complete month whose active uploads differ from the ones its snapshot was built
# MAGIC    from (`ops_monthly_snapshots`), or that has never been built.
# MAGIC 4. For each such month, oldest first and **the latest month last** (so the current tables end on the latest month):
# MAGIC    point `raw_*_current` at the month → `03_validate` → `00_reference` → `04_enrich` → `05_certify` →
# MAGIC    `06_dq_checks` (blocking failures stop here) → `07_snapshot_month`.
# MAGIC 5. `08_trends`: KPIs per month, month-over-month assessment, project-level changes.
# MAGIC
# MAGIC Widgets: `config_path` (blank = `config/pipeline_config.yml`; for the dev schema use
# MAGIC `config/pipeline_config_monthly_dev.yml`), `reprocess_months` (optional, e.g. `2026-07,2026-08`: rebuild these
# MAGIC months even if their uploads did not change, e.g. after a rule change).

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

import time  # noqa: E402

from ifc_common import load_contracts, load_order  # noqa: E402
from ifc_monthly import (REGISTRY, SNAPSHOTS, latest_month, month_label, months_to_process, parse_month,  # noqa: E402
                         point_current_views)

dbutils.widgets.text("reprocess_months", "", "Reprocess months (YYYY-MM, comma list; blank = auto)")  # noqa: F821
FORCE = {parse_month(m) for m in dbutils.widgets.get("reprocess_months").split(",") if m.strip()}  # noqa: F821
CONTRACTS = load_contracts(CFG["_contracts_dir"])
SOURCES = load_order(CONTRACTS)
ARGS = {"config_path": CONFIG_PATH}
MONTH_STEPS = ["./03_validate", "./00_reference", "./04_enrich", "./05_certify", "./06_dq_checks", "./07_snapshot_month"]


def run(notebook: str, timeout: int = 3600):
    t0 = time.time()
    print(f"  -> {notebook} ...", end=" ")
    out = dbutils.notebook.run(notebook, timeout, ARGS)  # noqa: F821
    print(f"done in {time.time() - t0:.0f}s")
    return out


def show(table: str, sql: str):
    """Display a query if its table exists (it may not before the first file arrives)."""
    if spark.catalog.tableExists(T(table)):
        display(spark.sql(sql))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 1–2. Gate and Raw load

# COMMAND ----------

gate_error = None
try:
    run("./01_schema_gate")
except Exception as e:  # held files: keep going with the accepted ones, report at the end
    gate_error = str(e).splitlines()[0][:500]
    print(f"\nSchema gate held at least one file: {gate_error}")
show("ops_schema_gate_log", f"""SELECT reporting_month, file_name, source, status, messages, moved_to
                                 FROM {T('ops_schema_gate_log')}
                                 WHERE run_id = (SELECT max_by(run_id, checked_at) FROM {T('ops_schema_gate_log')})""")

run("./02_load_raw")
show(REGISTRY, f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, source, source_file, rows_loaded, loaded_at,
                          is_active, superseded_by_load_id, check_message
                   FROM {T(REGISTRY)} ORDER BY reporting_month, source, loaded_at""")

# COMMAND ----------

# MAGIC %md ## 3–4. Rebuild every changed month

# COMMAND ----------

latest = latest_month(spark, CFG, SOURCES)
todo = sorted(set(months_to_process(spark, CFG, SOURCES)) | FORCE)
if latest is None:
    print("No complete month yet (each month needs every source file). Nothing to build.")
    order = []
else:
    order = [m for m in todo if m != latest]
    if todo:
        order.append(latest)   # always finish on the latest month so the current tables show it
print("Months to build: " + (", ".join(month_label(m) for m in order) or "none (no changes)"))

for n, m in enumerate(order):
    print(f"\n=== {month_label(m)} ===")
    point_current_views(spark, CFG, CONTRACTS, m)
    last = n == len(order) - 1
    for step in MONTH_STEPS:
        # ref_assumptions quotes figures of the current month only, so while back-filling older months it is rebuilt
        # just once, for the month processed last (enrichment only needs the vocabulary, which does not change).
        if step == "./00_reference" and not last and spark.catalog.tableExists(T("ref_product_vocabulary")):
            print("  -> ./00_reference skipped (older month; rebuilt for the latest month)")
            continue
        run(step)

# COMMAND ----------

# MAGIC %md ## 5. Trends

# COMMAND ----------

if order:
    run("./08_trends")
show(SNAPSHOTS, f"SELECT * FROM {T(SNAPSHOTS)} ORDER BY reporting_month")
show("kpi_latest_scorecard", f"SELECT * FROM {T('kpi_latest_scorecard')}")

if gate_error:
    raise RuntimeError(f"Done, but the schema gate held file(s); see ops_schema_gate_log. {gate_error}")
print(f"Done. Latest month: {month_label(latest) if latest else 'none'}.")
