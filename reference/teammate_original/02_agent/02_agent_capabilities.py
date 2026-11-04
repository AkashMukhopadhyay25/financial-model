# Databricks notebook source
# MAGIC %md
# MAGIC # 02_agent_capabilities — the governed tools the agents are allowed to use
# MAGIC
# MAGIC **Design principle:** the LLM never writes the SQL behind a decision. Decision figures come from **Unity Catalog
# MAGIC functions**: reviewed, versioned SQL with typed parameters, governed by grants and visible in lineage. The agent chooses
# MAGIC which tool to call and explains the result. Open-ended factual questions go to **Genie**, whose generated SQL is shown
# MAGIC to the user and marked "review recommended".
# MAGIC
# MAGIC | Tool (UC function) | Used for |
# MAGIC |---|---|
# MAGIC | `get_client_scorecard(client)` | One client's exposure, risk, performance and band |
# MAGIC | `get_client_projects(client)` | Project-level evidence behind a client assessment |
# MAGIC | `list_clients(band, top_n)` | Shortlists: who stands out positively or negatively |
# MAGIC | `board_risk_exposure()` | WS2 Board answer: Category A Past Due/Watchlist exposure and ECL |
# MAGIC | `simulate_exposure_reduction(client, cancel_share)` | "What if we cancel X% of undisbursed commitments?" |
# MAGIC | `get_assumptions(topic)` | Business definitions, so the agent can explain how a figure was computed |
# MAGIC | `data_quality_summary()` | Known data issues that affect an answer |
# MAGIC | **Genie space** | Any other portfolio question (WS1-style analytics) |

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

FQ = f"{CATALOG}.{SCHEMA}"

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.get_client_scorecard(client STRING COMMENT 'Client ID (e.g. CL-0087) or any part of the client name')
RETURNS TABLE (client_id STRING, client_name STRING, band STRING, band_evidence STRING, health_score DOUBLE,
               n_projects BIGINT, n_active BIGINT, n_pending BIGINT, n_closed BIGINT,
               n_performing BIGINT, n_watchlist BIGINT, n_past_due BIGINT, n_completed BIGINT, n_exited_at_loss BIGINT,
               exposure_weighted_risk_rating DOUBLE, max_risk_rating_active INT,
               current_disbursed_exposure_musd DOUBLE, undisbursed_commitment_musd DOUBLE, exposure_affected_musd DOUBLE,
               pipeline_unsigned_musd DOUBLE, past_due_disbursed_musd DOUBLE, watchlist_disbursed_musd DOUBLE,
               expected_credit_loss_musd DOUBLE, category_a_exposure_musd DOUBLE,
               primary_industry STRING, primary_region STRING, n_countries BIGINT)
COMMENT 'Client scorecard: exposure (USD M), credit risk, performance history and rule-based band (CONTINUE / MONITOR / REDUCE_OR_REVIEW). Use for any question about a specific client.'
RETURN
  SELECT client_id, client_name, band, band_evidence, health_score,
         n_projects, n_active, n_pending, n_closed, n_performing, n_watchlist, n_past_due, n_completed, n_exited_at_loss,
         exposure_weighted_risk_rating, max_risk_rating_active,
         current_disbursed_exposure_musd, undisbursed_commitment_musd, exposure_affected_musd,
         pipeline_unsigned_musd, past_due_disbursed_musd, watchlist_disbursed_musd,
         expected_credit_loss_musd, category_a_exposure_musd, primary_industry, primary_region, n_countries
  FROM {FQ}.gold_client_scorecard
  WHERE upper(client_id) = upper(trim(client)) OR lower(client_name) LIKE concat('%', lower(trim(client)), '%')
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.get_client_projects(client STRING COMMENT 'Client ID or any part of the client name')
RETURNS TABLE (client_name STRING, project_number BIGINT, project_name STRING, country STRING, industry STRING,
               status STRING, performance_status STRING, risk_flag STRING, internal_risk_rating INT,
               environmental_category STRING, approved_musd DOUBLE, disbursed_musd DOUBLE,
               current_exposure_musd DOUBLE, undisbursed_musd DOUBLE, expected_credit_loss_musd DOUBLE,
               days_since_last_review INT, project_url STRING)
COMMENT 'Project-level evidence for a client: status, performance, risk rating and exposure per project (USD M). Use to justify a recommendation.'
RETURN
  SELECT client_name, project_number, project_name, country, industry, status, performance_status, risk_flag,
         internal_risk_rating, environmental_category,
         round(total_approved_musd, 2), round(disbursed_musd, 2),
         round(current_disbursed_exposure_musd, 2), round(undisbursed_commitment_musd, 2), round(expected_credit_loss_musd, 2),
         days_since_last_review, project_url
  FROM {FQ}.gold_portfolio
  WHERE is_monitored
    AND (upper(client_id) = upper(trim(client)) OR lower(client_name) LIKE concat('%', lower(trim(client)), '%'))
  ORDER BY CASE risk_flag WHEN 'RED' THEN 1 WHEN 'AMBER' THEN 2 WHEN 'GREEN' THEN 3 ELSE 4 END, total_approved_musd DESC
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.list_clients(band_filter STRING COMMENT 'CONTINUE, MONITOR, REDUCE_OR_REVIEW or ALL',
                                            top_n INT COMMENT 'How many clients to return')
RETURNS TABLE (rank_in_list INT, client_id STRING, client_name STRING, band STRING, health_score DOUBLE,
               n_past_due BIGINT, n_watchlist BIGINT, exposure_weighted_risk_rating DOUBLE,
               exposure_affected_musd DOUBLE, distressed_disbursed_musd DOUBLE, expected_credit_loss_musd DOUBLE,
               band_evidence STRING)
COMMENT 'Ranked client shortlist. REDUCE_OR_REVIEW is ranked by distressed exposure (Past Due + Watchlist disbursed); other bands by exposure affected (disbursed + undisbursed). Use to find clients that stand out.'
RETURN
  SELECT * FROM (
    SELECT CAST(row_number() OVER (ORDER BY
             CASE WHEN band = 'REDUCE_OR_REVIEW' AND upper(band_filter) <> 'ALL'
                  THEN past_due_disbursed_musd + watchlist_disbursed_musd ELSE exposure_affected_musd END DESC) AS INT) AS rank_in_list,
           client_id, client_name, band, health_score, n_past_due, n_watchlist, exposure_weighted_risk_rating,
           exposure_affected_musd, round(past_due_disbursed_musd + watchlist_disbursed_musd, 2), expected_credit_loss_musd, band_evidence
    FROM {FQ}.gold_client_scorecard
    WHERE upper(band_filter) = 'ALL' OR band = upper(band_filter)
  ) WHERE rank_in_list <= top_n
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.board_risk_exposure()
RETURNS TABLE (performance_status STRING, projects BIGINT, clients BIGINT, approved_musd DOUBLE,
               disbursed_musd DOUBLE, undisbursed_commitment_musd DOUBLE, expected_credit_loss_musd DOUBLE)
COMMENT 'Board question (WS2): Category A projects that are Past Due or on the Watchlist - approved, disbursed, undisbursed and expected credit loss (60% of disbursed on Past Due). USD M. TOTAL row included.'
RETURN
  SELECT coalesce(performance_status, 'TOTAL'), count(*), count(DISTINCT client_id),
         round(sum(total_approved_musd), 2), round(sum(disbursed_musd), 2),
         round(sum(undisbursed_commitment_musd), 2), round(sum(expected_credit_loss_musd), 2)
  FROM {FQ}.gold_portfolio
  WHERE environmental_category = 'A' AND performance_status IN ('Past Due', 'Watchlist')
  GROUP BY ROLLUP(performance_status)
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.simulate_exposure_reduction(client STRING COMMENT 'Client ID or part of name',
                                                           cancel_share DOUBLE COMMENT 'Share of undisbursed commitments cancelled, 0 to 1')
RETURNS TABLE (client_id STRING, client_name STRING, current_disbursed_exposure_musd DOUBLE,
               undisbursed_commitment_musd DOUBLE, undisbursed_cancelled_musd DOUBLE,
               exposure_before_musd DOUBLE, exposure_after_musd DOUBLE, expected_credit_loss_musd DOUBLE)
COMMENT 'What-if: exposure before and after cancelling a share of a client''s undisbursed commitments (disbursed exposure is unchanged). USD M.'
RETURN
  SELECT client_id, client_name, current_disbursed_exposure_musd, undisbursed_commitment_musd,
         round(undisbursed_commitment_musd * least(greatest(cancel_share, 0), 1), 2),
         exposure_affected_musd,
         round(exposure_affected_musd - undisbursed_commitment_musd * least(greatest(cancel_share, 0), 1), 2),
         expected_credit_loss_musd
  FROM {FQ}.gold_client_scorecard
  WHERE upper(client_id) = upper(trim(client)) OR lower(client_name) LIKE concat('%', lower(trim(client)), '%')
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.get_assumptions(topic_filter STRING COMMENT 'Keyword, e.g. exposure, committed, region; empty string for all')
RETURNS TABLE (assumption_id STRING, topic STRING, statement STRING, rationale STRING)
COMMENT 'Business definitions and assumptions behind every figure. Use when asked how something was calculated.'
RETURN
  SELECT assumption_id, topic, statement, rationale FROM {FQ}.ref_assumptions
  WHERE trim(topic_filter) = '' OR lower(topic) LIKE concat('%', lower(topic_filter), '%')
        OR lower(statement) LIKE concat('%', lower(topic_filter), '%')
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {FQ}.data_quality_summary()
RETURNS TABLE (check_id STRING, severity STRING, description STRING, expected DOUBLE, actual DOUBLE, passed BOOLEAN, checked_at TIMESTAMP)
COMMENT 'Latest data-quality run: every check with expected vs actual. Use when asked whether the data can be trusted or about known data issues.'
RETURN
  SELECT check_id, severity, description, expected, actual, passed, checked_at FROM {FQ}.dq_results
  WHERE checked_at = (SELECT max(checked_at) FROM {FQ}.dq_results)
""")
print("UC functions created")

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Smoke tests: every tool returns data
# MAGIC SELECT * FROM list_clients('REDUCE_OR_REVIEW', 5);

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM board_risk_exposure();

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT * FROM list_clients('CONTINUE', 5);

# COMMAND ----------

# MAGIC %md
# MAGIC ## Audit log for agent answers
# MAGIC Every agent answer is written here with the tools and SQL it used and its review status. This is the traceability record a
# MAGIC Board secretary or auditor can consult.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE TABLE IF NOT EXISTS agent_audit_log (
# MAGIC   request_id STRING, asked_at TIMESTAMP, user_name STRING, question STRING, answer STRING,
# MAGIC   review_status STRING, tools_json STRING, model_endpoint STRING, latency_ms BIGINT)
# MAGIC COMMENT 'One row per agent answer: question, answer, tools and SQL used, review status (VALIDATED / REVIEW_RECOMMENDED / HUMAN_REVIEW_REQUIRED)';

# COMMAND ----------

# MAGIC %md
# MAGIC ## Genie space — the "what happened?" agent
# MAGIC Create it in the UI: **Genie → New**. Then:
# MAGIC 1. **Data:** add `gold_portfolio`, `gold_client_scorecard`, `ref_assumptions`, `dq_issue_log`, and only these. No bronze or silver tables.
# MAGIC 2. **Instructions:** paste the text printed by the next cell.
# MAGIC 3. **SQL queries / trusted assets:** add the WS1 SQL from `answers_register` (printed below) as example queries, and add the UC
# MAGIC    functions above as trusted functions.
# MAGIC 4. **Benchmarks:** add the questions from `genie_benchmark` with their SQL as ground truth, run the benchmark, and record the score
# MAGIC    for the README and the video.
# MAGIC 5. Copy the space ID from the URL into `GENIE_SPACE_ID` in `00_config`.

# COMMAND ----------

GENIE_INSTRUCTIONS = """You answer questions for IFC's CFO Office about its project portfolio. Amounts are USD millions.
Use gold_portfolio for project questions and gold_client_scorecard for client questions.
Business definitions (always apply; full list in ref_assumptions):
- Reporting date = max(reporting_date) = 2026-06-30. "Last N years" = approval_date > add_months(reporting date, -12*N) AND <= reporting date.
- Status filters only when the question states them; otherwise include all statuses, Dropped included.
- "Approved by the Board" = is_board_approved (approval_date not null). total_approved_musd is the Board total (proposed amount if not yet approved).
- "Committed" = is_committed (signed and not Dropped).
- Product mix uses loan_musd, equity_musd, guarantee_musd, risk_mgmt_musd. Totals use total_approved_musd.
- Region is already standardised; never group by region_as_reported.
- Time between lifecycle steps: use days_approval_to_signing, days_signing_to_investment, days_approval_to_investment (invalid sequences are already null).
- Renewable generation, capacity, MSME and described-product questions: use is_new_renewable_generation, new_capacity_mw, is_msme_financing, msme_target_group, described_product. Never search the description text with LIKE.
- Exposure: current_disbursed_exposure_musd (Active disbursed), undisbursed_commitment_musd, expected_credit_loss_musd (60% of disbursed on Past Due).
- project_number is NOT unique; identify projects by project_url, and show project_number and project_name.
- If text_attributes_need_review is true for rows in the answer, say that some classifications await human review.
Always show the SQL and state which definitions you applied."""
print(GENIE_INSTRUCTIONS)

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Benchmark set for Genie (and the evaluation set for the agent): the 30 questions with the SQL that produced the submitted answer
# MAGIC CREATE OR REPLACE TABLE genie_benchmark COMMENT 'WS1 questions with ground-truth SQL for Genie benchmarks and agent evaluation' AS
# MAGIC SELECT question_id, question, sql_text AS ground_truth_sql, assumptions
# MAGIC FROM answers_register WHERE workstream = 'WS1' AND question_id NOT LIKE '%detail%'
# MAGIC ORDER BY question_id;
# MAGIC SELECT * FROM genie_benchmark;

# COMMAND ----------

# MAGIC %md
# MAGIC ## Grants for the app's service principal (run once the app exists)
# MAGIC Replace `<app-service-principal>` with the application ID shown on the app page. Least privilege: read gold and ref tables,
# MAGIC execute the functions, write only the audit log. No access to bronze or silver.
# MAGIC ```sql
# MAGIC GRANT USE CATALOG ON CATALOG ifc_challenge TO `<app-service-principal>`;
# MAGIC GRANT USE SCHEMA ON SCHEMA ifc_challenge.portfolio TO `<app-service-principal>`;
# MAGIC GRANT SELECT ON TABLE ifc_challenge.portfolio.gold_portfolio TO `<app-service-principal>`;
# MAGIC GRANT SELECT ON TABLE ifc_challenge.portfolio.gold_client_scorecard TO `<app-service-principal>`;
# MAGIC GRANT SELECT ON TABLE ifc_challenge.portfolio.ref_assumptions TO `<app-service-principal>`;
# MAGIC GRANT SELECT ON TABLE ifc_challenge.portfolio.dq_results TO `<app-service-principal>`;
# MAGIC GRANT SELECT ON TABLE ifc_challenge.portfolio.ws3_recommendations TO `<app-service-principal>`;
# MAGIC GRANT EXECUTE ON SCHEMA ifc_challenge.portfolio TO `<app-service-principal>`;
# MAGIC GRANT MODIFY, SELECT ON TABLE ifc_challenge.portfolio.agent_audit_log TO `<app-service-principal>`;
# MAGIC ```
# MAGIC Plus: *Can use* on the SQL warehouse, *Can run* on the Genie space, *Can query* on the LLM serving endpoint (set as app resources).
