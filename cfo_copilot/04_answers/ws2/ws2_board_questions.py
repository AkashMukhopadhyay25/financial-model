# Databricks notebook source
# MAGIC %md
# MAGIC # WS2 — Integrated portfolio view: the two Board questions
# MAGIC
# MAGIC Answered from `gold_portfolio`, where each project is joined to its monitoring record on `project_url` (assumption A01).
# MAGIC
# MAGIC 1. *Which Category A projects are currently Past Due or on the Watchlist, who are the clients, and how much was approved for each?*
# MAGIC 2. *How much of IFC's disbursed capital is tied up in these projects, and how much should IFC set aside to cover potential losses on those that are Past Due?*
# MAGIC
# MAGIC **Expected credit loss (case brief, A11):** Past Due = default; loss = 60% of disbursed.

# COMMAND ----------

# MAGIC %run ../../00_setup/00_config

# COMMAND ----------

# MAGIC %md
# MAGIC ## Board question 1 — Category A projects that are Past Due or on the Watchlist

# COMMAND ----------

answer("WS2_Q1_projects", "Which Category A projects are currently Past Due or on the Watchlist, who are the clients, and how much was approved for each?", """
SELECT client_name, client_id, project_number, project_name, country, region, industry,
       performance_status, internal_risk_rating, status,
       round(total_approved_musd, 2) AS approved_musd,
       round(disbursed_musd, 2)      AS disbursed_musd,
       days_since_last_review
FROM gold_portfolio
WHERE environmental_category = 'A'
  AND performance_status IN ('Past Due', 'Watchlist')
ORDER BY performance_status, approved_musd DESC
""", "'Currently' = latest monitoring status (A17). Approved = Board total. All such projects are Active.")

answer("WS2_Q1_by_client", "Q1 grouped by client", """
SELECT client_name, client_id,
       count(*) AS projects,
       count_if(performance_status = 'Past Due')  AS past_due,
       count_if(performance_status = 'Watchlist') AS watchlist,
       round(sum(total_approved_musd), 2) AS approved_musd,
       round(sum(disbursed_musd), 2)      AS disbursed_musd
FROM gold_portfolio
WHERE environmental_category = 'A' AND performance_status IN ('Past Due', 'Watchlist')
GROUP BY client_name, client_id
ORDER BY approved_musd DESC
""", "")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Board question 2 — disbursed capital tied up and loss provision

# COMMAND ----------

ws2 = answer("WS2_Q2_exposure_and_ecl", "How much of IFC's disbursed capital is tied up in these projects, and how much should IFC set aside to cover potential losses on those that are Past Due?", """
SELECT coalesce(performance_status, 'TOTAL')        AS status_label,
       count(*)                                     AS projects,
       round(sum(total_approved_musd), 2)           AS approved_musd,
       round(sum(disbursed_musd), 2)                AS disbursed_capital_tied_up_musd,
       round(sum(undisbursed_commitment_musd), 2)   AS undisbursed_commitment_musd,
       round(sum(expected_credit_loss_musd), 2)     AS expected_credit_loss_musd
FROM gold_portfolio
WHERE environmental_category = 'A' AND performance_status IN ('Past Due', 'Watchlist')
GROUP BY ROLLUP(performance_status)
ORDER BY status_label = 'TOTAL', status_label
""", "ECL = 60% x disbursed on Past Due projects only; Watchlist projects carry no provision under the brief's simplified model (A11). Undisbursed commitments are shown because they are further exposure IFC may still fund (A10).")

answer("WS2_Q2_context", "Context: the same provision for the whole portfolio, not only Category A", """
SELECT environmental_category,
       count_if(performance_status = 'Past Due')                      AS past_due_projects,
       round(sum(CASE WHEN performance_status = 'Past Due' THEN disbursed_musd END), 2) AS past_due_disbursed_musd,
       round(sum(expected_credit_loss_musd), 2)                       AS expected_credit_loss_musd
FROM gold_portfolio
GROUP BY ROLLUP(environmental_category)
ORDER BY environmental_category NULLS LAST
""", "Helps the Board see what share of total provisioning need sits in Category A projects.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Reconciliation against an independent calculation
# MAGIC The same figures were computed directly from the two source CSVs outside Databricks (no shared code).
# MAGIC Agreement shows the join, the typing and the business rules are correct.

# COMMAND ----------

INDEPENDENT = {"projects": 95, "approved_musd": 15473.36, "disbursed_capital_tied_up_musd": 11447.52,
               "expected_credit_loss_musd": 3311.72}
total = [r for r in ws2.collect() if r["status_label"] == "TOTAL"][0].asDict()
for k, expected in INDEPENDENT.items():
    ok = abs(float(total[k]) - expected) <= 0.05
    print(f"{'OK  ' if ok else 'DIFF'} {k}: pipeline={total[k]} independent={expected}")

# COMMAND ----------

persist_answers("WS2")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Board-ready summary (fill from the outputs above)
# MAGIC * **95** Category A projects are Past Due (35) or on the Watchlist (60), across **61** clients, all Active, with **$15,473M** approved.
# MAGIC * **$11,448M** of disbursed capital is tied up in them: $5,520M Past Due and $5,928M Watchlist.
# MAGIC * Recommended provision on the Past Due projects: **$3,312M** (60% × $5,520M).
# MAGIC * Further exposure: undisbursed commitments on these projects (table above) should be reviewed before any further drawdown.
# MAGIC
# MAGIC *Figures reconciled independently; see the cell above. Method: `answers_register` rows with workstream `WS2`.*
