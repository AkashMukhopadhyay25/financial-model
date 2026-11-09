# Databricks notebook source
# MAGIC %md
# MAGIC # 07_snapshot_month — keep every month
# MAGIC
# MAGIC `certified_investment_portfolio` always holds one month: the one just processed. This notebook copies it into
# MAGIC **`certified_investment_portfolio_history`** (one row per project per reporting month), replacing **only that month's
# MAGIC rows**. So when October is re-uploaded and reprocessed, October's history is overwritten with the corrected data
# MAGIC and every other month stays exactly as it was.
# MAGIC
# MAGIC | Output | What it holds |
# MAGIC |---|---|
# MAGIC | `certified_investment_portfolio_history` | Every column of the certified table plus `projects_load_id`, `monitoring_load_id`, `_snapshot_at`. Partitioned by `reporting_month`. |
# MAGIC | `ops_monthly_snapshots` | One row per month: which uploads it was built from, row and quarantine counts, the data-quality check run, when. The pipeline compares it with `ops_monthly_loads` to see which months need reprocessing. |
# MAGIC
# MAGIC Run after `06_dq_checks` (a month whose blocking checks fail never reaches the history).

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from ifc_common import load_contracts  # noqa: E402
from ifc_monthly import SNAPSHOTS, month_label  # noqa: E402

CONTRACTS = load_contracts(CFG["_contracts_dir"])
CERT = T("certified_investment_portfolio")
HIST = T("certified_investment_portfolio_history")
RAW = {s: T(c["targets"]["raw"]) + "_current" for s, c in CONTRACTS.items()}
QUA = {s: T(c["targets"]["quarantine"]) for s, c in CONTRACTS.items()}

months = [r[0] for r in spark.sql(f"SELECT DISTINCT reporting_month FROM {CERT}").collect()]
assert len(months) == 1 and months[0] is not None, f"{CERT} should hold exactly one reporting month, found {months}"
MONTH = months[0]
LOADS = {s: spark.sql(f"SELECT first(_load_id) AS id, first(_source_file) AS f, count(*) AS n FROM {RAW[s]}").first()
         for s in CONTRACTS}
print(f"Snapshotting {month_label(MONTH)}: " + ", ".join(f"{s} = {LOADS[s]['f']}" for s in CONTRACTS))

# COMMAND ----------

# MAGIC %md ## History table: replace this month only

# COMMAND ----------

from pyspark.sql import functions as F  # noqa: E402

snap = (spark.table(CERT)
        .withColumn("projects_load_id", F.lit(LOADS["projects"]["id"]))
        .withColumn("monitoring_load_id", F.lit(LOADS["monitoring"]["id"]))
        .withColumn("_snapshot_at", F.current_timestamp()))

if not spark.catalog.tableExists(HIST):
    snap.write.partitionBy("reporting_month").saveAsTable(HIST)
    spark.sql(f"COMMENT ON TABLE {HIST} IS 'Certified investment portfolio for every reporting month: one row per project per "
              "month. A re-uploaded month replaces only its own rows. Use for trends and month-to-month comparison; "
              "certified_investment_portfolio holds the latest month only.'")
else:
    (snap.write.mode("overwrite")
         .option("replaceWhere", f"reporting_month = DATE'{MONTH.isoformat()}'")
         .option("mergeSchema", "true")
         .saveAsTable(HIST))

display(spark.sql(f"""
  SELECT reporting_month, count(*) AS projects, round(sum(total_approved_musd), 2) AS total_approved_musd,
         min(_snapshot_at) AS snapshot_at
  FROM {HIST} GROUP BY reporting_month ORDER BY reporting_month"""))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Month register: `ops_monthly_snapshots`

# COMMAND ----------

dq = spark.sql(f"""
  SELECT run_id, count_if(NOT passed AND severity = 'blocking') AS blocking_failed, count_if(NOT passed) AS not_passed
  FROM {T('ops_dq_checks')} WHERE checked_at = (SELECT max(checked_at) FROM {T('ops_dq_checks')})
  GROUP BY run_id""").first() if spark.catalog.tableExists(T("ops_dq_checks")) else None

row = {
    "reporting_month": MONTH,
    "projects_load_id": LOADS["projects"]["id"], "projects_source_file": LOADS["projects"]["f"],
    "monitoring_load_id": LOADS["monitoring"]["id"], "monitoring_source_file": LOADS["monitoring"]["f"],
    "projects_rows_received": int(LOADS["projects"]["n"]), "monitoring_rows_received": int(LOADS["monitoring"]["n"]),
    "projects_quarantined": spark.table(QUA["projects"]).count(),
    "monitoring_quarantined": spark.table(QUA["monitoring"]).count(),
    "certified_rows": spark.table(CERT).count(),
    "dq_run_id": dq["run_id"] if dq else None,
    "dq_checks_not_passed": int(dq["not_passed"]) if dq else None,
}
schema = ("reporting_month DATE, projects_load_id STRING, projects_source_file STRING, monitoring_load_id STRING, "
          "monitoring_source_file STRING, projects_rows_received BIGINT, monitoring_rows_received BIGINT, "
          "projects_quarantined BIGINT, monitoring_quarantined BIGINT, certified_rows BIGINT, dq_run_id STRING, "
          "dq_checks_not_passed BIGINT")
reg = T(SNAPSHOTS)
spark.sql(f"""CREATE TABLE IF NOT EXISTS {reg} ({schema}, snapshot_at TIMESTAMP)
              COMMENT 'One row per reporting month in certified_investment_portfolio_history: the uploads it was built from, row and quarantine counts, the data-quality check run. Replaced when a month is reprocessed.'""")
spark.sql(f"DELETE FROM {reg} WHERE reporting_month = DATE'{MONTH.isoformat()}'")
spark.createDataFrame([tuple(row.values())], schema).withColumn("snapshot_at", F.current_timestamp()) \
     .write.mode("append").saveAsTable(reg)
display(spark.table(reg).orderBy("reporting_month"))  # noqa: F821
