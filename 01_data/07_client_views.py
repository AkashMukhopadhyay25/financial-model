# Databricks notebook source
# MAGIC %md
# MAGIC # 07_client_views — client scorecard and early-warning signals
# MAGIC
# MAGIC Builds two client-level tables from **`certified_investment_portfolio`** (one row per client):
# MAGIC
# MAGIC | Table | Content | Used by |
# MAGIC |---|---|---|
# MAGIC | `certified_client_scorecard` | Exposure (current, undisbursed, pipeline), credit risk, performance history, data-quality counts and a rule-based band: CONTINUE / MONITOR / REDUCE_OR_REVIEW (A15) | WS3, the app's Client intelligence page, Genie |
# MAGIC | `certified_early_warning` | Clients with Active projects that show at least one emerging-risk signal, with the signals, priority and suggested action (A22) | the app's Early warning page |
# MAGIC
# MAGIC No opaque "AI score": every component is a ratio an analyst can recompute, and every threshold is a policy parameter
# MAGIC in `config/pipeline_config.yml` (`business.client_bands`, `business.health_score_weights`, `business.early_warning`).
# MAGIC The SQL lives in `00_setup/portfolio_sql.py`, so the app's local preview uses exactly the same definitions.
# MAGIC
# MAGIC Run after `05_certify` (and `00_reference`, which records A15 and A22 in `ref_assumptions`).

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from portfolio_sql import client_scorecard_sql, early_warning_signals, early_warning_sql  # noqa: E402

P = T("certified_investment_portfolio")
SCORECARD = T("certified_client_scorecard")
EARLY_WARNING = T("certified_early_warning")

spark.sql(f"CREATE OR REPLACE TABLE {SCORECARD} "
          "COMMENT 'One row per monitored client: exposure (current, undisbursed, pipeline), credit risk, performance history, "
          "data-quality counts and a rule-based band CONTINUE / MONITOR / REDUCE_OR_REVIEW (A15). Amounts in USD millions.' "
          f"AS {client_scorecard_sql(P, CFG)}")
print(f"{SCORECARD}: {spark.table(SCORECARD).count()} clients")

spark.sql(f"CREATE OR REPLACE TABLE {EARLY_WARNING} "
          "COMMENT 'Clients with Active projects showing at least one emerging-risk signal (A22): signals, priority "
          "(HIGH/MEDIUM/REVIEW) and suggested action. Signals are prompts for human investigation, not predictions of default.' "
          f"AS {early_warning_sql(SCORECARD, CFG)}")
print(f"{EARLY_WARNING}: {spark.table(EARLY_WARNING).count()} clients with at least one signal")

# COMMAND ----------

# MAGIC %md ## Column comments (Genie reads these)

# COMMAND ----------

SCORECARD_COMMENTS = {
    "client_id": "Client identifier, e.g. CL-0087.",
    "client_name": "Client (company or institution IFC invests in or lends to).",
    "n_projects": "Monitored projects of this client (every non-Dropped project is monitored).",
    "n_active": "Active projects.",
    "n_past_due": "Projects whose latest performance status is Past Due.",
    "n_watchlist": "Projects whose latest performance status is Watchlist.",
    "n_exited_at_loss": "Closed projects exited at a loss.",
    "approved_musd": "Sum of Board-approved totals, USD millions (A08).",
    "current_disbursed_exposure_musd": "Disbursed amount on Active projects, USD millions (A09).",
    "undisbursed_commitment_musd": "Approved but not yet disbursed on Active and signed Pending projects, USD millions (A10).",
    "pipeline_unsigned_musd": "Approved total of unsigned Pending projects, USD millions.",
    "expected_credit_loss_musd": "60% of disbursed on Past Due projects, USD millions (A11).",
    "exposure_affected_musd": "Current disbursed exposure + undisbursed commitments: what a decision on this client affects, USD millions.",
    "exposure_weighted_risk_rating": "Internal risk rating of Active projects weighted by disbursed amount (1 best - 6 worst).",
    "n_active_rating_5_6": "Active projects with internal risk rating 5 or 6.",
    "n_review_overdue_active": "Active projects overdue for periodic review (A18).",
    "n_projects_needing_review": "Projects with at least one open data-quality flag.",
    "n_high_severity_flags": "Projects whose most severe data-quality flag is high.",
    "top_country": "Country holding the largest share of the client's current exposure.",
    "top_country_exposure_share": "Share of current exposure in top_country (0-1).",
    "distress_share": "Past Due + Watchlist disbursed as a share of current exposure (0-1).",
    "closed_loss_rate": "Share of finished projects exited at a loss (0-1).",
    "health_score": "0-100, higher is healthier; formula in assumption A15.",
    "band": "CONTINUE, MONITOR or REDUCE_OR_REVIEW; rules in assumption A15.",
    "band_evidence": "Plain-language evidence for the band.",
    "materiality_rank_in_band": "Rank by exposure_affected_musd within the band (1 = largest).",
}
EW_COMMENTS = {col: f"Signal: {label} (A22)." for col, label, _ in early_warning_signals(CFG)}
EW_COMMENTS.update({
    "signal_count": "Number of signals triggered (0-5).",
    "triggered_by": "Signals triggered, in words.",
    "priority": "HIGH, MEDIUM or REVIEW, from signal_count (A22).",
    "suggested_action": "Escalation, updated review or investigation. Never an automatic investment decision.",
    "review_owner": "Team that reviews the alert.",
})

for table, comments in [(SCORECARD, SCORECARD_COMMENTS), (EARLY_WARNING, EW_COMMENTS)]:
    cols = set(spark.table(table).columns)
    for col, text in comments.items():
        if col in cols:
            spark.sql(f"ALTER TABLE {table} ALTER COLUMN {col} COMMENT '{text.replace(chr(39), chr(39) * 2)}'")
    spark.sql(f"ALTER TABLE {table} SET TAGS ('layer' = 'certified', 'domain' = 'cfo_portfolio', 'data_classification' = 'synthetic')")
print("Comments and tags written")

# COMMAND ----------

# MAGIC %md ## Human-review log for the app
# MAGIC The app's "Flag for review" and "Mark reviewed" buttons append here (who, when, what, note). Created once, never
# MAGIC replaced. Grant the app's service principal `MODIFY` on this table (see `app/README.md`).

# COMMAND ----------

spark.sql(f"""CREATE TABLE IF NOT EXISTS {T('ops_review_requests')} (
  requested_at TIMESTAMP, requested_by STRING, entity_type STRING, entity_id STRING, entity_name STRING,
  action STRING, note STRING, source_page STRING)
COMMENT 'Human-in-the-loop log from the CFO Intelligence app: review flags and alerts marked reviewed.'""")

# COMMAND ----------

# MAGIC %md ## Check: bands and signals

# COMMAND ----------

display(spark.sql(f"""
SELECT band, count(*) AS clients, round(sum(current_disbursed_exposure_musd), 0) AS current_exposure_musd,
       round(sum(undisbursed_commitment_musd), 0) AS undisbursed_musd, round(sum(expected_credit_loss_musd), 0) AS ecl_musd
FROM {SCORECARD} GROUP BY band ORDER BY band"""))
display(spark.sql(f"""
SELECT priority, count(*) AS clients, round(sum(exposure_affected_musd), 0) AS exposure_affected_musd
FROM {EARLY_WARNING} GROUP BY priority ORDER BY CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END"""))
