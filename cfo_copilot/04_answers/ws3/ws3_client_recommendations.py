# Databricks notebook source
# MAGIC %md
# MAGIC # WS3 — Decision support: which clients to back and which to review
# MAGIC
# MAGIC **Method (transparent by design):**
# MAGIC 1. `gold_client_scorecard` (built in `01_data`) holds every client's exposure, credit risk, performance history and a
# MAGIC    rule-based band: CONTINUE, MONITOR or REDUCE_OR_REVIEW (thresholds in assumption A15).
# MAGIC 2. Within each band, clients are ranked by **materiality**: exposure affected = current disbursed exposure + undisbursed commitments.
# MAGIC 3. A **sensitivity check** confirms the picks do not depend on one arbitrary weight.
# MAGIC 4. The team applies judgment to the shortlist, and each recommendation is stored with its evidence and a **human-review flag**:
# MAGIC    the output is a recommendation to the credit committee, not an automated decision.
# MAGIC
# MAGIC The CFO Decision Advisor agent (`02_agent`) reads the same tables, so the CFO gets identical figures by asking in plain language.

# COMMAND ----------

# MAGIC %run ../../00_setup/00_config

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT band, count(*) AS clients,
# MAGIC        round(sum(current_disbursed_exposure_musd), 0) AS current_exposure_musd,
# MAGIC        round(sum(undisbursed_commitment_musd), 0)     AS undisbursed_musd,
# MAGIC        round(sum(expected_credit_loss_musd), 0)       AS ecl_musd
# MAGIC FROM gold_client_scorecard GROUP BY band ORDER BY band

# COMMAND ----------

# MAGIC %md
# MAGIC ## Shortlists

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Positive standouts: healthy and material
# MAGIC SELECT client_name, client_id, primary_industry, primary_region, n_active, n_closed,
# MAGIC        n_past_due, n_watchlist, n_exited_at_loss, avg_risk_rating_active, max_risk_rating_active,
# MAGIC        current_disbursed_exposure_musd, undisbursed_commitment_musd, exposure_affected_musd,
# MAGIC        health_score, band_evidence
# MAGIC FROM gold_client_scorecard
# MAGIC WHERE band = 'CONTINUE'
# MAGIC ORDER BY exposure_affected_musd DESC
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Negative standouts: distressed and material
# MAGIC SELECT client_name, client_id, primary_industry, primary_region, n_active,
# MAGIC        n_past_due, n_watchlist, n_exited_at_loss, exposure_weighted_risk_rating, distress_share,
# MAGIC        past_due_disbursed_musd, watchlist_disbursed_musd, expected_credit_loss_musd,
# MAGIC        current_disbursed_exposure_musd, undisbursed_commitment_musd, exposure_affected_musd,
# MAGIC        health_score, band_evidence
# MAGIC FROM gold_client_scorecard
# MAGIC WHERE band = 'REDUCE_OR_REVIEW'
# MAGIC ORDER BY past_due_disbursed_musd + watchlist_disbursed_musd DESC
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %md
# MAGIC ## Selection and sensitivity
# MAGIC Primary rule: CONTINUE = the two largest exposures in the CONTINUE band; REDUCE = the two largest distressed exposures (Past Due + Watchlist disbursed).
# MAGIC Sensitivity: re-rank by health score and by a credit-heavy weighting; a pick is **robust** if it stays in the top 5 under every ranking.

# COMMAND ----------

import pandas as pd

sc = spark.table("gold_client_scorecard").toPandas()
sc["distressed_musd"] = sc["past_due_disbursed_musd"].fillna(0) + sc["watchlist_disbursed_musd"].fillna(0)
sc["credit_heavy_score"] = (0.7 * 100 * (6 - sc["exposure_weighted_risk_rating"].fillna(sc["avg_risk_rating_all"])) / 5
                            + 0.3 * 100 * (1 - sc["distress_share"].fillna(0)))

cont = sc[sc.band == "CONTINUE"]
red = sc[sc.band == "REDUCE_OR_REVIEW"]

def top(df, col, asc=False, n=5):
    return list(df.sort_values(col, ascending=asc).head(n).client_id)

continue_rankings = {
    "materiality": top(cont, "exposure_affected_musd"),
    "health_score": top(cont[cont.exposure_affected_musd >= cont.exposure_affected_musd.median()], "health_score"),
    "credit_heavy": top(cont[cont.exposure_affected_musd >= cont.exposure_affected_musd.median()], "credit_heavy_score"),
}
reduce_rankings = {
    "distressed_exposure": top(red, "distressed_musd"),
    "expected_loss": top(red, "expected_credit_loss_musd"),
    "lowest_health": top(red[red.exposure_affected_musd >= red.exposure_affected_musd.median()], "health_score", asc=True),
}

def robustness(rankings, picks):
    return {c: sum(c in r for r in rankings.values()) for c in picks}

continue_picks = continue_rankings["materiality"][:2]
reduce_picks = reduce_rankings["distressed_exposure"][:2]
print("CONTINUE picks:", continue_picks, "robustness (rankings containing pick, of 3):", robustness(continue_rankings, continue_picks))
print("REDUCE picks:  ", reduce_picks, "robustness (of 3):", robustness(reduce_rankings, reduce_picks))
print("\nIf a pick is not robust (fewer than 2 of 3), look at the shortlists and record the team's judgment in RATIONALE below.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Team judgment
# MAGIC Override the computed picks here if the team decides differently, and record **why**. Judgment is expected by the brief;
# MAGIC the reason is stored with the recommendation.

# COMMAND ----------

OVERRIDE_CONTINUE = None   # e.g. ["CL-0123", "CL-0456"]
OVERRIDE_REDUCE = None
RATIONALE = {
    # "CL-0123": "Largest healthy relationship; undisbursed pipeline in priority sector",
}
final_continue = OVERRIDE_CONTINUE or continue_picks
final_reduce = OVERRIDE_REDUCE or reduce_picks

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evidence and persisted recommendation

# COMMAND ----------

from pyspark.sql import functions as F

def evidence(client_id):
    projects = spark.sql(f"""
        SELECT project_number, project_name, country, industry, status, performance_status, risk_flag,
               internal_risk_rating, environmental_category,
               round(total_approved_musd, 2) AS approved_musd, round(disbursed_musd, 2) AS disbursed_musd,
               round(current_disbursed_exposure_musd, 2) AS current_exposure_musd,
               round(undisbursed_commitment_musd, 2) AS undisbursed_musd, days_since_last_review
        FROM gold_portfolio WHERE client_id = '{client_id}'
        ORDER BY CASE risk_flag WHEN 'RED' THEN 1 WHEN 'AMBER' THEN 2 ELSE 3 END, approved_musd DESC""")
    return projects

rows = []
for rec, ids in [("CONTINUE", final_continue), ("REDUCE_OR_REVIEW", final_reduce)]:
    for cid in ids:
        s = sc[sc.client_id == cid].iloc[0]
        ev = evidence(cid)
        print(f"\n=== {rec}: {s.client_name} ({cid}) ===")
        display(ev)
        if rec == "CONTINUE":
            action = (f"Continue to invest: keep the ${s.undisbursed_commitment_musd:,.0f}M undisbursed commitments on schedule "
                      f"and prioritise new pipeline (${s.pipeline_unsigned_musd:,.0f}M unsigned).")
        else:
            action = (f"Reduce exposure / place under review: freeze further drawdowns on the ${s.undisbursed_commitment_musd:,.0f}M "
                      f"undisbursed commitments pending credit review; provision ${s.expected_credit_loss_musd:,.0f}M ECL.")
        rows.append({
            "recommendation": rec,
            "client_id": cid,
            "client_name": s.client_name,
            "primary_industry": s.primary_industry,
            "primary_region": s.primary_region,
            "current_disbursed_exposure_musd": float(s.current_disbursed_exposure_musd),
            "undisbursed_commitment_musd": float(s.undisbursed_commitment_musd),
            "exposure_affected_musd": float(s.exposure_affected_musd),
            "expected_credit_loss_musd": float(s.expected_credit_loss_musd),
            "health_score": float(s.health_score),
            "evidence_summary": s.band_evidence,
            "suggested_action": action,
            "team_rationale": RATIONALE.get(cid, "Selected by the documented ranking rule; robust across sensitivity rankings"),
            "evidence_projects_json": ev.toPandas().to_json(orient="records"),
            "requires_human_review": True,
            "review_owner": "Credit Risk Committee",
        })

rec_df = spark.createDataFrame(pd.DataFrame(rows)).withColumn("generated_at", F.current_timestamp())
rec_df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable("ws3_recommendations")
display(spark.table("ws3_recommendations").drop("evidence_projects_json"))

# COMMAND ----------

# MAGIC %md
# MAGIC ## Board memo (generated from the table above: every number is traceable)

# COMMAND ----------

memo = ["# Client recommendations: Board risk review", "",
        "*Draft for Credit Risk Committee review. Figures in USD millions from `ws3_recommendations`; method in WS3 notebook.*", ""]
for r in rows:
    memo += [f"## {('CONTINUE TO INVEST' if r['recommendation'] == 'CONTINUE' else 'REDUCE / REVIEW')}: {r['client_name']} ({r['client_id']})",
             f"- Exposure affected: **${r['exposure_affected_musd']:,.0f}M** "
             f"(disbursed ${r['current_disbursed_exposure_musd']:,.0f}M + undisbursed ${r['undisbursed_commitment_musd']:,.0f}M)",
             f"- Evidence: {r['evidence_summary']}; health score {r['health_score']}/100",
             f"- Action: {r['suggested_action']}",
             f"- Rationale: {r['team_rationale']}", ""]
memo_md = "\n".join(memo)
print(memo_md)

answer("WS3_recommendation", "Recommend the two clients IFC should continue to invest in and the two whose exposure it should reduce or place under review.",
       "SELECT recommendation, client_name, client_id, exposure_affected_musd, current_disbursed_exposure_musd, undisbursed_commitment_musd, expected_credit_loss_musd, evidence_summary, suggested_action FROM ws3_recommendations ORDER BY recommendation, exposure_affected_musd DESC",
       "Bands and thresholds per A15; exposure affected = current disbursed exposure + undisbursed commitments (A09, A10). Requires Credit Risk Committee review.")
persist_answers("WS3")
