# Databricks notebook source
# MAGIC %md
# MAGIC # 01_load_and_prepare — governed data foundation
# MAGIC
# MAGIC Turns the two IFC files into governed, validated, documented tables that every answer and every agent tool reads from.
# MAGIC
# MAGIC ```
# MAGIC Volume (raw CSV) ──► bronze_*  (exact copy, all strings, lineage columns)
# MAGIC                 ──► silver_* (typed, trimmed, standardised, row-level DQ flags)
# MAGIC                 ──► ref_*    (assumptions, region mapping, product vocabulary, reviewer overrides)
# MAGIC                 ──► gold_project_text_features (LLM extraction cross-checked by deterministic rules)
# MAGIC                 ──► gold_portfolio        (one row per project: portfolio + monitoring + derived metrics)
# MAGIC                 ──► gold_client_scorecard (one row per client: exposure, risk, performance, band)
# MAGIC                 ──► dq_results / dq_issue_log (evidence that every check ran and what it found)
# MAGIC ```
# MAGIC
# MAGIC **Prerequisite:** upload `synthetic_ifc_projects_5000.csv` and `synthetic_project_monitoring.csv` to the volume
# MAGIC (Catalog → `ifc_challenge.portfolio.raw_files` → *Upload to this volume*).
# MAGIC
# MAGIC **Re-runnable:** every step uses `CREATE OR REPLACE`; LLM extractions are cached and only new or changed descriptions are sent to the model.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Bronze — load the files exactly as delivered
# MAGIC
# MAGIC **Data-quality finding #1 (ingestion):** 475 project descriptions contain line breaks inside quoted text.
# MAGIC A naive CSV reader, including the *Create table from upload* UI, splits these projects across several rows and shifts
# MAGIC their columns. We therefore read with `multiLine=true` and RFC-4180 quote escaping, and reconcile row counts and
# MAGIC control totals against figures computed independently from the source files (section 8).

# COMMAND ----------

from pyspark.sql import functions as F

PROJECT_COLUMNS = {
    "Date Disclosed": "date_disclosed",
    "Project Name": "project_name",
    "Document Type": "document_type",
    "Project Number": "project_number",
    "Project Url": "project_url",
    "Product Line": "product_line",
    "Region": "region",
    "Country": "country",
    "Project Description": "project_description",
    "Industry": "industry",
    "Environmental Category": "environmental_category",
    "Department": "department",
    "Status": "status",
    "Projected Board Date": "projected_board_date",
    "IFC Approval Date": "approval_date",
    "IFC Signed Date": "signed_date",
    "IFC Invested Date": "invested_date",
    "IFC investment for Risk Management(Million - USD)": "risk_mgmt_musd",
    "IFC investment for Guarantee(Million - USD)": "guarantee_musd",
    "IFC investment for Loan(Million - USD)": "loan_musd",
    "IFC investment for Equity(Million - USD)": "equity_musd",
    "Total IFC investment as approved by Board(Million - USD)": "total_approved_musd",
    "WB Country Code": "wb_country_code",
    "As of Date": "as_of_date",
}

MONITORING_COLUMNS = {
    "Project Url": "project_url",
    "Project Number": "project_number",
    "Client ID": "client_id",
    "Client Name": "client_name",
    "Internal Risk Rating": "internal_risk_rating",
    "Currency": "currency",
    "Climate Flag": "climate_flag",
    "IFC Disbursed Amount(Million - USD)": "disbursed_musd",
    "Performance Status": "performance_status",
    "Days Since Last Review": "days_since_last_review",
}

def load_bronze(path: str, mapping: dict, table: str, expected_rows: int):
    raw = (spark.read.format("csv")
           .option("header", "true")
           .option("multiLine", "true")      # descriptions contain line breaks
           .option("quote", '"')
           .option("escape", '"')            # RFC-4180: "" inside quoted text
           .option("inferSchema", "false")   # bronze keeps source text; typing happens in silver
           .load(path))
    missing = set(mapping) - set(raw.columns)
    unexpected = set(raw.columns) - set(mapping)
    assert not missing, f"{path}: missing expected columns {missing}"
    assert not unexpected, f"{path}: unexpected columns {unexpected}"
    bronze = raw.select(
        *[F.col(f"`{src}`").alias(dst) for src, dst in mapping.items()],
        F.col("_metadata.file_path").alias("_source_file"),
        F.col("_metadata.file_modification_time").alias("_source_modified_at"),
        F.current_timestamp().alias("_ingested_at"),
    )
    bronze.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(table)
    n = spark.table(table).count()
    assert n == expected_rows, f"{table}: expected {expected_rows} rows, found {n}"
    print(f"{table}: {n} rows loaded from {path}")

load_bronze(PROJECTS_FILE, PROJECT_COLUMNS, "bronze_projects", 5000)
load_bronze(MONITORING_FILE, MONITORING_COLUMNS, "bronze_monitoring", 3768)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Reference tables — assumptions and mappings are data, not hidden code
# MAGIC
# MAGIC Storing assumptions and mappings as tables means Genie, the agent and the README all quote the **same** definitions,
# MAGIC and a CFO-office owner can change a rule without touching code.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE ref_assumptions (
# MAGIC   assumption_id STRING, topic STRING, statement STRING, rationale STRING)
# MAGIC COMMENT 'Business definitions and assumptions applied consistently across every answer, Genie and the agent';
# MAGIC
# MAGIC INSERT INTO ref_assumptions VALUES
# MAGIC ('A01','Join key','Project Portfolio and Project Monitoring are joined on Project Url (one-to-zero-or-one).','Project Url is unique in both files. Project Number is not unique (3,559 distinct values across 5,000 projects) and cannot identify a project.'),
# MAGIC ('A02','Reporting date','The reporting date is the latest As of Date in the data (2026-06-30). "Last N years" means an approval date after (reporting date minus N years) and on or before the reporting date.','Answers must not change depending on the day they are run.'),
# MAGIC ('A03','Status filters','Status filters are applied only where a question states them. A question that does not mention status includes every project, Dropped included.','A literal, predictable rule; the alternative would be a different judgment call per question.'),
# MAGIC ('A04','Approved by the Board','A project counts as Board-approved when IFC Approval Date is present. For projects not yet approved, the Total column holds the proposed amount.','Data dictionary definition of the Total column.'),
# MAGIC ('A05','Committed','A project is committed once its legal agreements are signed (IFC Signed Date present) unless its Status is Dropped.','Definition given in question 6.'),
# MAGIC ('A06','Region labels','The labels "Middle East & North Africa" (21 projects) and "Latin America & Caribbean" (22) are not in the data dictionary; they are restated to "Middle East" and "Latin America", the region every other record for those countries uses. The original label is kept in region_as_reported.','Otherwise regional totals split the same countries across two names.'),
# MAGIC ('A07','Lifecycle intervals','Approval-to-signing-to-investment intervals use only records whose dates are in lifecycle order. 37 projects signed before approval are excluded from averages and logged in dq_issue_log.','A negative interval is a recording error, not a business fact.'),
# MAGIC ('A08','Product amounts','Product-mix answers use the four allocation columns; total answers use the Board total. 146 projects differ by more than $1M; they are reported in Q28 and not corrected.','The source cannot tell us which figure is right; the CFO Office must decide.'),
# MAGIC ('A09','Current exposure','Current disbursed exposure is the disbursed amount on Active projects. Closed projects have concluded; Pending projects have no disbursement.','Data dictionary and glossary.'),
# MAGIC ('A10','Undisbursed commitments','Active: approved minus disbursed (floored at 0). Pending and signed: the full approved amount. All other projects: 0.','A signed agreement obliges IFC to fund; an unsigned Pending project is pipeline, reported separately.'),
# MAGIC ('A11','Expected credit loss','Past Due projects are treated as in default; expected loss = 60% of their disbursed amount.','Simplified model given in the case brief.'),
# MAGIC ('A12','Text-derived attributes','Renewable generation, capacity (MW), MSME focus and the product named in the description are extracted by an LLM and cross-checked against deterministic rules. Disagreements are flagged for human review; reviewer overrides in ref_text_feature_overrides take precedence.','Free text is ambiguous; two independent methods plus review make the result trustworthy.'),
# MAGIC ('A13','New renewable generation','The main purpose is to build, develop or expand the client''s own renewable generation (solar, wind, hydro, geothermal). Excludes transmission and distribution, standalone battery storage, gas plants and rooftop solar for own use. Capacity is new MW only (GW x 1,000; for expansions only the added MW).','Questions 13 and 24 ask about new generation, not anything mentioning renewables.'),
# MAGIC ('A14','MSME financing','The main purpose is financing micro, small or medium enterprises (including "small firms" and "small companies") through a Finance-sector client. Excludes projects where SMEs are suppliers or incidental beneficiaries, are explicitly excluded, where loans go to households, and green lending only to corporate clients. Farms and factories expanding their own capacity are not MSME financing even when they benefit rural areas.','Question 25 asks about financing for MSMEs. Review of 228 LLM/rule disagreements showed the LLM was right on small-firm lending phrasings and wrong on agribusiness, manufacturing and corporate-only lending; both corrections are encoded.'),
# MAGIC ('A15','Client bands','REDUCE_OR_REVIEW: 2+ Past Due projects, or 25%+ of current exposure Past Due/Watchlist, or exposure-weighted risk rating 4.5 or worse. CONTINUE: no Past Due or Watchlist, every active rating 3 or better, at most 5% of closed projects exited at a loss, and 3+ active projects. Otherwise MONITOR.','Transparent thresholds the CFO Office can tune; they are policy parameters, not model outputs.'),
# MAGIC ('A16','Currency','All amounts are USD millions as supplied. The Currency field is informational; no FX conversion is applied.','Data dictionary.'),
# MAGIC ('A17','Snapshot dates','Records carry one of five As of Dates (2025-06-30 to 2026-06-30). Each project''s latest available record is used; records older than the reporting date are flagged as stale.','Only one record per project exists.');

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE ref_region_mapping (region_as_reported STRING, region STRING, note STRING)
# MAGIC COMMENT 'Restates region labels that are not in the data dictionary (assumption A06)';
# MAGIC INSERT INTO ref_region_mapping VALUES
# MAGIC ('Middle East & North Africa', 'Middle East',   'Not a dictionary value; same countries appear under Middle East elsewhere'),
# MAGIC ('Latin America & Caribbean',  'Latin America', 'Not a dictionary value; same countries appear under Latin America elsewhere');
# MAGIC
# MAGIC CREATE OR REPLACE TABLE ref_product_vocabulary (phrase STRING, product STRING)
# MAGIC COMMENT 'Financing instruments named in project descriptions and the Product Line they belong to (used for Q26)';
# MAGIC INSERT INTO ref_product_vocabulary VALUES
# MAGIC ('long-term loan','Loan'), ('senior loan','Loan'), ('a-loan','Loan'), ('debt financing package','Loan'),
# MAGIC ('equity investment','Equity'), ('minority shareholding','Equity'), ('equity stake','Equity'), ('equity participation','Equity'),
# MAGIC ('credit guarantee facility','Guarantee'), ('partial credit guarantee','Guarantee'), ('risk-sharing guarantee','Guarantee'), ('guarantee','Guarantee'),
# MAGIC ('risk management facility','Risk Management'), ('currency hedging facility','Risk Management'),
# MAGIC ('interest rate swap','Risk Management'), ('derivative hedging product','Risk Management');
# MAGIC
# MAGIC -- Human-in-the-loop: a reviewer's decision on a flagged text attribute wins over both methods.
# MAGIC CREATE TABLE IF NOT EXISTS ref_text_feature_overrides (
# MAGIC   project_url STRING, attribute STRING, value STRING, reviewer STRING, reviewed_at TIMESTAMP, note STRING)
# MAGIC COMMENT 'Reviewer decisions on flagged text attributes (attribute in: is_new_renewable_generation, new_capacity_mw, is_msme_financing, msme_target_group, described_product)';

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Silver — typed, standardised, every anomaly flagged at row level

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_projects
# MAGIC COMMENT 'IFC Project Portfolio: one row per project, typed and standardised, with row-level data-quality flags'
# MAGIC AS
# MAGIC WITH typed AS (
# MAGIC   SELECT
# MAGIC     trim(project_url)                                          AS project_url,
# MAGIC     try_cast(project_number AS BIGINT)                         AS project_number,
# MAGIC     trim(project_name)                                         AS project_name,
# MAGIC     trim(document_type)                                        AS document_type,
# MAGIC     try_cast(date_disclosed AS DATE)                           AS date_disclosed,
# MAGIC     trim(product_line)                                         AS product_line,
# MAGIC     trim(region)                                               AS region_as_reported,
# MAGIC     trim(country)                                              AS country,
# MAGIC     upper(trim(wb_country_code))                               AS wb_country_code,
# MAGIC     trim(industry)                                             AS industry,
# MAGIC     upper(trim(environmental_category))                        AS environmental_category,
# MAGIC     upper(trim(department))                                    AS department,
# MAGIC     trim(status)                                               AS status,
# MAGIC     try_cast(projected_board_date AS DATE)                     AS projected_board_date,
# MAGIC     try_cast(approval_date AS DATE)                            AS approval_date,
# MAGIC     try_cast(signed_date AS DATE)                              AS signed_date,
# MAGIC     try_cast(invested_date AS DATE)                            AS invested_date,
# MAGIC     try_cast(as_of_date AS DATE)                               AS as_of_date,
# MAGIC     coalesce(try_cast(risk_mgmt_musd AS DOUBLE), 0)            AS risk_mgmt_musd,
# MAGIC     coalesce(try_cast(guarantee_musd AS DOUBLE), 0)            AS guarantee_musd,
# MAGIC     coalesce(try_cast(loan_musd AS DOUBLE), 0)                 AS loan_musd,
# MAGIC     coalesce(try_cast(equity_musd AS DOUBLE), 0)               AS equity_musd,
# MAGIC     try_cast(total_approved_musd AS DOUBLE)                    AS total_approved_musd,
# MAGIC     project_description,
# MAGIC     trim(regexp_replace(project_description, '\\s+', ' '))     AS description_clean,
# MAGIC     _source_file, _ingested_at
# MAGIC   FROM bronze_projects
# MAGIC )
# MAGIC SELECT
# MAGIC   t.* EXCEPT (region_as_reported),
# MAGIC   coalesce(m.region, t.region_as_reported)                     AS region,
# MAGIC   t.region_as_reported,
# MAGIC   t.risk_mgmt_musd + t.guarantee_musd + t.loan_musd + t.equity_musd AS product_alloc_sum_musd,
# MAGIC   t.total_approved_musd - (t.risk_mgmt_musd + t.guarantee_musd + t.loan_musd + t.equity_musd) AS alloc_gap_musd,
# MAGIC   (CASE WHEN t.risk_mgmt_musd > 0 THEN 1 ELSE 0 END + CASE WHEN t.guarantee_musd > 0 THEN 1 ELSE 0 END
# MAGIC    + CASE WHEN t.loan_musd > 0 THEN 1 ELSE 0 END + CASE WHEN t.equity_musd > 0 THEN 1 ELSE 0 END) AS product_count,
# MAGIC   -- row-level data-quality flags
# MAGIC   m.region IS NOT NULL                                         AS dq_region_restated,
# MAGIC   t.signed_date < t.approval_date                              AS dq_signed_before_approval,
# MAGIC   t.invested_date < t.signed_date                              AS dq_invested_before_signed,
# MAGIC   (t.invested_date IS NOT NULL AND t.signed_date IS NULL)      AS dq_invested_without_signing_date,
# MAGIC   abs(t.total_approved_musd - (t.risk_mgmt_musd + t.guarantee_musd + t.loan_musd + t.equity_musd)) > 1.0 AS dq_allocation_gap,
# MAGIC   t.as_of_date < max(t.as_of_date) OVER ()                     AS dq_stale_snapshot
# MAGIC FROM typed t
# MAGIC LEFT JOIN ref_region_mapping m ON t.region_as_reported = m.region_as_reported;

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE silver_monitoring
# MAGIC COMMENT 'IFC Project Monitoring: one row per monitored project, typed, with row-level data-quality flags'
# MAGIC AS
# MAGIC SELECT
# MAGIC   trim(project_url)                                   AS project_url,
# MAGIC   try_cast(project_number AS BIGINT)                  AS project_number,
# MAGIC   upper(trim(client_id))                              AS client_id,
# MAGIC   trim(client_name)                                   AS client_name,
# MAGIC   try_cast(internal_risk_rating AS INT)               AS internal_risk_rating,
# MAGIC   upper(trim(currency))                               AS currency,
# MAGIC   trim(climate_flag)                                  AS climate_flag,
# MAGIC   lower(trim(climate_flag)) = 'yes'                   AS is_climate_related,
# MAGIC   try_cast(disbursed_musd AS DOUBLE)                  AS disbursed_musd,
# MAGIC   nullif(trim(performance_status), '')                AS performance_status,
# MAGIC   try_cast(days_since_last_review AS INT)             AS days_since_last_review,
# MAGIC   NOT (try_cast(internal_risk_rating AS INT) BETWEEN 1 AND 6) AS dq_risk_rating_out_of_range,
# MAGIC   _source_file, _ingested_at
# MAGIC FROM bronze_monitoring;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Text features — the four [Challenge] questions need facts that exist only in free text
# MAGIC
# MAGIC Two independent methods, then reconciliation:
# MAGIC 1. **Deterministic rules** (regex on the description's first sentence plus a product vocabulary). Fast, free and explainable, but brittle.
# MAGIC 2. **LLM extraction** with `ai_query` and a strict JSON contract. Handles negations such as *"rather than SMEs"* and
# MAGIC    *"Unlike the sponsor's earlier solar plant"*, transmission lines that connect *other sponsors'* wind farms, GW→MW conversion, and expansions.
# MAGIC 3. **Reconcile:** a reviewer override wins, then the LLM, then the rule. Any disagreement sets `needs_review = true`, and
# MAGIC    disagreements are counted in `dq_results`.
# MAGIC
# MAGIC Extraction runs **once in the pipeline**, not at question time, so every user gets the same answer (consistency requirement).

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE rule_text_features
# MAGIC COMMENT 'Deterministic (regex/vocabulary) extraction of text attributes; baseline used to cross-check the LLM'
# MAGIC AS
# MAGIC WITH base AS (
# MAGIC   SELECT project_url, industry, description_clean AS d,
# MAGIC          coalesce(description_clean, '') <> '' AS has_description,
# MAGIC          -- first sentence; the look-behind stops "S.A." in company names from ending the sentence
# MAGIC          coalesce(nullif(regexp_extract(description_clean, '^(.*?(?<!S\\.A)\\.)(\\s|$)', 1), ''), description_clean) AS s1
# MAGIC   FROM silver_projects
# MAGIC ),
# MAGIC flags AS (
# MAGIC   SELECT *,
# MAGIC     (s1 RLIKE '(?i)solar|wind|hydro|geothermal|run-of-river'
# MAGIC      AND NOT s1 RLIKE '(?i)transmission line|distribution network|battery storage system|gas-fired|rooftop|own use') AS rb_is_new_renewable_generation,
# MAGIC     (industry = 'Finance'
# MAGIC      AND d RLIKE '(?i)\\bMSMEs?\\b|\\bSMEs?\\b|small and medium|small businesses|small firms|small companies|micro, small|micro-entrepreneurs'
# MAGIC      AND NOT d RLIKE '(?i)rather than SMEs|buy inputs from|households and small businesses|outside the scope|Unlike the bank.s SME') AS rb_is_msme_financing,
# MAGIC     -- lending only to corporate clients is not MSME financing, even when it is green lending
# MAGIC     (d RLIKE '(?i)corporate clients'
# MAGIC      AND NOT d RLIKE '(?i)\\bSMEs?\\b|small and medium|small businesses|small firms|small companies')  AS rb_corporate_only
# MAGIC   FROM base
# MAGIC ),
# MAGIC product AS (
# MAGIC   SELECT project_url, product AS rb_described_product FROM (
# MAGIC     SELECT b.project_url, v.product,
# MAGIC            row_number() OVER (PARTITION BY b.project_url ORDER BY instr(lower(b.d), v.phrase), length(v.phrase) DESC) AS rn
# MAGIC     FROM base b JOIN ref_product_vocabulary v ON instr(lower(b.d), v.phrase) > 0
# MAGIC   ) WHERE rn = 1
# MAGIC )
# MAGIC SELECT
# MAGIC   f.project_url,
# MAGIC   f.industry,
# MAGIC   f.has_description,
# MAGIC   f.rb_corporate_only,
# MAGIC   f.rb_is_new_renewable_generation,
# MAGIC   CASE WHEN f.rb_is_new_renewable_generation THEN
# MAGIC     CASE
# MAGIC       WHEN f.s1 RLIKE 'further [0-9]'
# MAGIC         THEN try_cast(regexp_replace(regexp_extract(f.s1, 'further ([0-9][0-9,.]*)\\s*(MW|megawatts?)', 1), ',', '') AS DOUBLE)
# MAGIC       WHEN f.s1 RLIKE '[0-9]\\s*GW'
# MAGIC         THEN 1000 * try_cast(regexp_replace(regexp_extract(f.s1, '([0-9][0-9,.]*)\\s*GW', 1), ',', '') AS DOUBLE)
# MAGIC       ELSE try_cast(regexp_replace(regexp_extract(f.s1, '([0-9][0-9,.]*)\\s*(MW(?!h)|megawatts?)', 1), ',', '') AS DOUBLE)
# MAGIC     END
# MAGIC   END AS rb_new_capacity_mw,
# MAGIC   f.rb_is_msme_financing,
# MAGIC   CASE WHEN f.rb_is_msme_financing THEN
# MAGIC     CASE
# MAGIC       WHEN f.d RLIKE '(?i)women'                                   THEN 'Women-owned businesses'
# MAGIC       WHEN f.d RLIKE '(?i)rural|agricultur|farm-based'             THEN 'Rural & agricultural enterprises'
# MAGIC       WHEN f.d RLIKE '(?i)energy efficiency|climate-friendly'      THEN 'Small businesses investing in green equipment'
# MAGIC       WHEN f.d RLIKE '(?i)micro-entrepreneurs|small traders'       THEN 'Micro-entrepreneurs & small traders'
# MAGIC       ELSE 'General MSME lending'
# MAGIC     END
# MAGIC   END AS rb_msme_target_group,
# MAGIC   p.rb_described_product
# MAGIC FROM flags f LEFT JOIN product p USING (project_url);

# COMMAND ----------

# MAGIC %md
# MAGIC ### LLM extraction (cached, incremental)
# MAGIC Only descriptions not yet extracted (new projects or changed text, detected by hash) are sent to the model.
# MAGIC Model, timestamp and raw response are stored for audit.

# COMMAND ----------

spark.sql("""
CREATE TABLE IF NOT EXISTS llm_text_extractions (
  project_url STRING, description_hash STRING, model_endpoint STRING, extracted_at TIMESTAMP,
  raw_response STRING, error_message STRING,
  is_new_renewable_generation BOOLEAN, new_capacity_mw DOUBLE, is_msme_financing BOOLEAN,
  msme_target_group STRING, described_product STRING)
COMMENT 'Audit trail of LLM extraction from project descriptions (one row per project per description version)'
""")

EXTRACTION_PROMPT = (
    "You extract facts from one IFC project description. Reply with ONLY a JSON object with exactly these keys. "
    "is_new_renewable_generation: true only if the MAIN purpose of this project is to build, develop or expand renewable "
    "power generation capacity (solar, wind, hydro, geothermal) for the client; false for transmission or distribution "
    "lines, battery storage on its own, gas or thermal plants, rooftop or on-site solar for own use, and lending programmes. "
    "new_capacity_mw: the NEW generation capacity added by this project in MW as a number (convert GW to MW; for an "
    "expansion use only the added capacity; ignore MWh of storage); null if not stated or not applicable. "
    "is_msme_financing: true only if the main purpose is financing micro, small or medium enterprises (MSMEs, SMEs, small "
    "businesses, micro-entrepreneurs); false if SMEs are only suppliers or incidental beneficiaries, are explicitly "
    "excluded, or the loans go to households. "
    "msme_target_group: one of [Women-owned businesses, Rural & agricultural enterprises, Small businesses investing in "
    "green equipment, Micro-entrepreneurs & small traders, General MSME lending], or null if not MSME financing. "
    "described_product: the principal IFC financing instrument named in the text as one of [Loan, Equity, Guarantee, "
    "Risk Management], or null if none is named; swaps, hedging and derivatives are Risk Management; if the text says "
    "X alongside a smaller Y, return X. Description: "
)

def sql_literal(text: str) -> str:
    """Single-quoted Spark SQL literal with quotes and backslashes escaped."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"

if RUN_LLM_EXTRACTION:
    # Descriptions not yet extracted successfully (new, changed, or failed/unparseable last time).
    todo = spark.sql("""
      SELECT s.project_url, s.description_clean, sha2(s.description_clean, 256) AS description_hash
      FROM silver_projects s
      LEFT ANTI JOIN (SELECT * FROM llm_text_extractions
                      WHERE error_message IS NULL AND is_new_renewable_generation IS NOT NULL) e
        ON e.project_url = s.project_url AND e.description_hash = sha2(s.description_clean, 256)
      WHERE coalesce(s.description_clean, '') <> ''   -- 31 projects have no description: nothing to extract
      ORDER BY s.project_url""")
    if LLM_EXTRACTION_LIMIT:
        todo = todo.limit(int(LLM_EXTRACTION_LIMIT))
    pending = todo.collect()   # at most 5,000 short rows
    print(f"{len(pending)} descriptions to extract in batches of {LLM_BATCH_SIZE} ({LLM_PARALLELISM} parallel calls)")

# Small inputs land in a single Spark partition, which makes ai_query call the model one row at a time.
# Repartitioning each batch runs LLM_PARALLELISM calls concurrently; committing per batch saves progress.
for start in (range(0, len(pending), LLM_BATCH_SIZE) if RUN_LLM_EXTRACTION else []):
    spark.createDataFrame(pending[start:start + LLM_BATCH_SIZE], schema=todo.schema) \
         .repartition(LLM_PARALLELISM).createOrReplaceTempView("llm_todo_batch")
    spark.sql(f"""
    INSERT INTO llm_text_extractions
    WITH called AS (
      SELECT project_url, description_hash,
             ai_query('{LLM_ENDPOINT}',
                      concat({sql_literal(EXTRACTION_PROMPT)}, description_clean),
                      modelParameters => named_struct('temperature', 0.0, 'max_tokens', 250),
                      failOnError => false) AS r
      FROM llm_todo_batch
    ),
    parsed AS (
      SELECT project_url, description_hash, r.result AS raw_response, r.errorMessage AS error_message,
             from_json(regexp_extract(r.result, '(?s)\\\\{{.*\\\\}}', 0),
               'is_new_renewable_generation BOOLEAN, new_capacity_mw DOUBLE, is_msme_financing BOOLEAN, msme_target_group STRING, described_product STRING') AS j
      FROM called
    )
    SELECT project_url, description_hash, '{LLM_ENDPOINT}', current_timestamp(), raw_response, error_message,
           j.is_new_renewable_generation, j.new_capacity_mw, j.is_msme_financing, j.msme_target_group,
           CASE WHEN j.described_product IN ('Loan','Equity','Guarantee','Risk Management') THEN j.described_product END
    FROM parsed
    """)
    print(f"  committed {min(start + LLM_BATCH_SIZE, len(pending))}/{len(pending)}")

if RUN_LLM_EXTRACTION:
    display(spark.sql("""
      SELECT count(*) AS extractions, count_if(error_message IS NOT NULL) AS model_errors,
             count_if(error_message IS NULL AND is_new_renewable_generation IS NULL) AS unparseable
      FROM llm_text_extractions"""))
else:
    print("RUN_LLM_EXTRACTION = False: text features will come from rules only and are all flagged for review")

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE gold_project_text_features
# MAGIC COMMENT 'Text-derived project attributes: reviewer override > LLM > rule. needs_review flags disagreement or missing LLM output (assumption A12)'
# MAGIC AS
# MAGIC WITH llm AS (
# MAGIC   SELECT * FROM (
# MAGIC     SELECT e.*, row_number() OVER (PARTITION BY e.project_url ORDER BY e.extracted_at DESC) AS rn
# MAGIC     FROM llm_text_extractions e
# MAGIC     JOIN silver_projects s ON s.project_url = e.project_url AND e.description_hash = sha2(s.description_clean, 256)
# MAGIC     WHERE e.error_message IS NULL AND e.is_new_renewable_generation IS NOT NULL
# MAGIC   ) WHERE rn = 1
# MAGIC ),
# MAGIC ovr AS (
# MAGIC   SELECT project_url,
# MAGIC     max_by(CASE WHEN attribute = 'is_new_renewable_generation' THEN value END, CASE WHEN attribute = 'is_new_renewable_generation' THEN reviewed_at END) AS o_renew,
# MAGIC     max_by(CASE WHEN attribute = 'new_capacity_mw' THEN value END, CASE WHEN attribute = 'new_capacity_mw' THEN reviewed_at END) AS o_mw,
# MAGIC     max_by(CASE WHEN attribute = 'is_msme_financing' THEN value END, CASE WHEN attribute = 'is_msme_financing' THEN reviewed_at END) AS o_msme,
# MAGIC     max_by(CASE WHEN attribute = 'msme_target_group' THEN value END, CASE WHEN attribute = 'msme_target_group' THEN reviewed_at END) AS o_group,
# MAGIC     max_by(CASE WHEN attribute = 'described_product' THEN value END, CASE WHEN attribute = 'described_product' THEN reviewed_at END) AS o_product
# MAGIC   FROM ref_text_feature_overrides GROUP BY project_url
# MAGIC ),
# MAGIC j AS (
# MAGIC   SELECT r.*, l.is_new_renewable_generation AS llm_renew, l.new_capacity_mw AS llm_mw,
# MAGIC          -- Guard (A14): the first full run showed the LLM labelling farms, factories and corporate-only
# MAGIC          -- green lending as MSME financing. MSME financing must come from a Finance-sector project.
# MAGIC          CASE WHEN l.is_msme_financing AND (r.industry <> 'Finance' OR r.rb_corporate_only) THEN false
# MAGIC               ELSE l.is_msme_financing END AS llm_msme,
# MAGIC          l.msme_target_group AS llm_group, l.described_product AS llm_product,
# MAGIC          l.model_endpoint, l.extracted_at, o.o_renew, o.o_mw, o.o_msme, o.o_group, o.o_product
# MAGIC   FROM rule_text_features r
# MAGIC   LEFT JOIN llm l USING (project_url)
# MAGIC   LEFT JOIN ovr o USING (project_url)
# MAGIC )
# MAGIC SELECT
# MAGIC   project_url,
# MAGIC   coalesce(try_cast(o_renew AS BOOLEAN), llm_renew, rb_is_new_renewable_generation)           AS is_new_renewable_generation,
# MAGIC   CASE WHEN coalesce(try_cast(o_renew AS BOOLEAN), llm_renew, rb_is_new_renewable_generation)
# MAGIC        THEN coalesce(try_cast(o_mw AS DOUBLE), llm_mw, CASE WHEN llm_renew IS NULL THEN rb_new_capacity_mw END) END AS new_capacity_mw,
# MAGIC   coalesce(try_cast(o_msme AS BOOLEAN), llm_msme, rb_is_msme_financing)                       AS is_msme_financing,
# MAGIC   CASE WHEN coalesce(try_cast(o_msme AS BOOLEAN), llm_msme, rb_is_msme_financing)
# MAGIC        THEN coalesce(o_group, llm_group, rb_msme_target_group) END                            AS msme_target_group,
# MAGIC   coalesce(o_product, llm_product, rb_described_product)                                      AS described_product,
# MAGIC   rb_is_new_renewable_generation, rb_new_capacity_mw, rb_is_msme_financing, rb_msme_target_group, rb_described_product,
# MAGIC   llm_renew, llm_mw, llm_msme, llm_group, llm_product, model_endpoint, extracted_at,
# MAGIC   CASE
# MAGIC     WHEN NOT has_description THEN 'no_description'
# MAGIC     WHEN llm_renew IS NULL THEN 'llm_missing'
# MAGIC     WHEN llm_renew <> rb_is_new_renewable_generation THEN 'renewable_disagreement'
# MAGIC     WHEN llm_renew AND abs(coalesce(llm_mw, -1) - coalesce(rb_new_capacity_mw, -1)) > 1 THEN 'capacity_disagreement'
# MAGIC     WHEN llm_msme <> rb_is_msme_financing THEN 'msme_disagreement'
# MAGIC     WHEN NOT (llm_product <=> rb_described_product) THEN 'product_disagreement'
# MAGIC   END                                                                                          AS review_reason,
# MAGIC   (has_description AND o_renew IS NULL AND o_mw IS NULL AND o_msme IS NULL AND o_product IS NULL AND (
# MAGIC       llm_renew IS NULL
# MAGIC    OR llm_renew <> rb_is_new_renewable_generation
# MAGIC    OR (llm_renew AND abs(coalesce(llm_mw, -1) - coalesce(rb_new_capacity_mw, -1)) > 1)
# MAGIC    OR llm_msme <> rb_is_msme_financing
# MAGIC    OR NOT (llm_product <=> rb_described_product)))                                             AS needs_review,
# MAGIC   o_renew IS NOT NULL OR o_mw IS NOT NULL OR o_msme IS NOT NULL OR o_group IS NOT NULL OR o_product IS NOT NULL AS has_reviewer_override
# MAGIC FROM j;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Gold — one governed table per business question type

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE gold_portfolio
# MAGIC COMMENT 'One row per IFC project: portfolio record + monitoring record (joined on project_url) + derived exposure, lifecycle and text attributes. Primary table for Genie and the agent. Amounts in USD millions.'
# MAGIC AS
# MAGIC SELECT
# MAGIC   p.project_url, p.project_number, p.project_name, p.document_type, p.date_disclosed,
# MAGIC   p.product_line, p.region, p.region_as_reported, p.country, p.wb_country_code, p.industry,
# MAGIC   p.environmental_category, p.department, p.status,
# MAGIC   p.projected_board_date, p.approval_date, p.signed_date, p.invested_date, p.as_of_date,
# MAGIC   max(p.as_of_date) OVER ()                                         AS reporting_date,
# MAGIC   p.loan_musd, p.equity_musd, p.guarantee_musd, p.risk_mgmt_musd,
# MAGIC   p.total_approved_musd, p.product_alloc_sum_musd, p.alloc_gap_musd, p.product_count,
# MAGIC   p.product_count > 1                                               AS is_multi_product,
# MAGIC   p.approval_date IS NOT NULL                                       AS is_board_approved,
# MAGIC   p.signed_date IS NOT NULL                                         AS is_signed,
# MAGIC   p.invested_date IS NOT NULL                                       AS is_invested,
# MAGIC   p.signed_date IS NOT NULL AND p.status <> 'Dropped'               AS is_committed,
# MAGIC   -- monitoring
# MAGIC   m.project_url IS NOT NULL                                         AS is_monitored,
# MAGIC   m.client_id, m.client_name, m.internal_risk_rating, m.currency, m.climate_flag, m.is_climate_related,
# MAGIC   m.disbursed_musd, m.performance_status, m.days_since_last_review,
# MAGIC   -- exposure (assumptions A09, A10, A11)
# MAGIC   CASE WHEN p.status = 'Active' THEN coalesce(m.disbursed_musd, 0) ELSE 0 END AS current_disbursed_exposure_musd,
# MAGIC   CASE
# MAGIC     WHEN p.status = 'Active' THEN greatest(p.total_approved_musd - coalesce(m.disbursed_musd, 0), 0)
# MAGIC     WHEN p.status = 'Pending' AND p.signed_date IS NOT NULL THEN p.total_approved_musd
# MAGIC     ELSE 0 END                                                      AS undisbursed_commitment_musd,
# MAGIC   CASE WHEN p.status = 'Pending' AND p.signed_date IS NULL THEN p.total_approved_musd ELSE 0 END AS pipeline_unsigned_musd,
# MAGIC   CASE WHEN m.performance_status = 'Past Due' THEN ecl_loss_rate * coalesce(m.disbursed_musd, 0) ELSE 0 END AS expected_credit_loss_musd,
# MAGIC   CASE m.performance_status
# MAGIC     WHEN 'Past Due' THEN 'RED' WHEN 'Watchlist' THEN 'AMBER' WHEN 'Performing' THEN 'GREEN'
# MAGIC     WHEN 'Completed' THEN 'CLOSED_OK' WHEN 'Exited at a loss' THEN 'CLOSED_LOSS'
# MAGIC     ELSE 'NOT_APPLICABLE' END                                       AS risk_flag,
# MAGIC   -- lifecycle (assumption A07: only valid sequences)
# MAGIC   CASE WHEN p.signed_date >= p.approval_date THEN datediff(p.signed_date, p.approval_date) END   AS days_approval_to_signing,
# MAGIC   CASE WHEN p.invested_date >= p.signed_date THEN datediff(p.invested_date, p.signed_date) END   AS days_signing_to_investment,
# MAGIC   CASE WHEN p.invested_date >= p.approval_date THEN datediff(p.invested_date, p.approval_date) END AS days_approval_to_investment,
# MAGIC   -- text attributes
# MAGIC   tf.is_new_renewable_generation, tf.new_capacity_mw, tf.is_msme_financing, tf.msme_target_group, tf.described_product,
# MAGIC   tf.needs_review AS text_attributes_need_review,
# MAGIC   -- data quality
# MAGIC   p.dq_region_restated, p.dq_signed_before_approval, p.dq_invested_before_signed,
# MAGIC   p.dq_invested_without_signing_date, p.dq_allocation_gap, p.dq_stale_snapshot,
# MAGIC   p.project_description, p.description_clean
# MAGIC FROM silver_projects p
# MAGIC LEFT JOIN silver_monitoring m ON p.project_url = m.project_url
# MAGIC LEFT JOIN gold_project_text_features tf ON p.project_url = tf.project_url;

# COMMAND ----------

# MAGIC %md
# MAGIC ### Client scorecard — transparent, rule-based (assumption A15)
# MAGIC No opaque "AI score": every component is a ratio a finance analyst can recompute, and the band thresholds are policy
# MAGIC parameters the CFO Office owns. The agent **explains** the scorecard; it does not invent it.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE gold_client_scorecard
# MAGIC COMMENT 'One row per client: exposure (current, undisbursed, pipeline), credit risk, performance history and a rule-based band (CONTINUE / MONITOR / REDUCE_OR_REVIEW). Amounts in USD millions.'
# MAGIC AS
# MAGIC WITH agg AS (
# MAGIC   SELECT
# MAGIC     client_id,
# MAGIC     max(client_name)                                                    AS client_name,
# MAGIC     count(*)                                                            AS n_projects,
# MAGIC     count_if(status = 'Active')                                         AS n_active,
# MAGIC     count_if(status = 'Pending')                                        AS n_pending,
# MAGIC     count_if(status = 'Closed')                                         AS n_closed,
# MAGIC     count_if(performance_status = 'Performing')                         AS n_performing,
# MAGIC     count_if(performance_status = 'Watchlist')                          AS n_watchlist,
# MAGIC     count_if(performance_status = 'Past Due')                           AS n_past_due,
# MAGIC     count_if(performance_status = 'Completed')                          AS n_completed,
# MAGIC     count_if(performance_status = 'Exited at a loss')                   AS n_exited_at_loss,
# MAGIC     round(sum(total_approved_musd), 2)                                  AS approved_musd,
# MAGIC     round(sum(coalesce(disbursed_musd, 0)), 2)                          AS lifetime_disbursed_musd,
# MAGIC     round(sum(current_disbursed_exposure_musd), 2)                      AS current_disbursed_exposure_musd,
# MAGIC     round(sum(undisbursed_commitment_musd), 2)                          AS undisbursed_commitment_musd,
# MAGIC     round(sum(pipeline_unsigned_musd), 2)                               AS pipeline_unsigned_musd,
# MAGIC     round(sum(CASE WHEN performance_status = 'Past Due'  THEN disbursed_musd ELSE 0 END), 2) AS past_due_disbursed_musd,
# MAGIC     round(sum(CASE WHEN performance_status = 'Watchlist' THEN disbursed_musd ELSE 0 END), 2) AS watchlist_disbursed_musd,
# MAGIC     round(sum(expected_credit_loss_musd), 2)                            AS expected_credit_loss_musd,
# MAGIC     round(sum(CASE WHEN environmental_category = 'A' THEN current_disbursed_exposure_musd + undisbursed_commitment_musd ELSE 0 END), 2) AS category_a_exposure_musd,
# MAGIC     round(avg(CASE WHEN status = 'Active' THEN internal_risk_rating END), 2) AS avg_risk_rating_active,
# MAGIC     max(CASE WHEN status = 'Active' THEN internal_risk_rating END)          AS max_risk_rating_active,
# MAGIC     round(sum(CASE WHEN status = 'Active' THEN internal_risk_rating * disbursed_musd END)
# MAGIC           / nullif(sum(CASE WHEN status = 'Active' THEN disbursed_musd END), 0), 2) AS exposure_weighted_risk_rating,
# MAGIC     round(avg(internal_risk_rating), 2)                                 AS avg_risk_rating_all,
# MAGIC     round(avg(CASE WHEN status = 'Active' THEN days_since_last_review END), 0) AS avg_days_since_review_active,
# MAGIC     max(CASE WHEN status = 'Active' THEN days_since_last_review END)    AS max_days_since_review_active,
# MAGIC     count(DISTINCT country)                                             AS n_countries,
# MAGIC     count(DISTINCT industry)                                            AS n_industries,
# MAGIC     mode(industry)                                                      AS primary_industry,
# MAGIC     mode(region)                                                        AS primary_region,
# MAGIC     round(avg(CASE WHEN is_climate_related THEN 1.0 ELSE 0.0 END), 3)   AS climate_share
# MAGIC   FROM gold_portfolio
# MAGIC   WHERE is_monitored
# MAGIC   GROUP BY client_id
# MAGIC ),
# MAGIC scored AS (
# MAGIC   SELECT *,
# MAGIC     round(current_disbursed_exposure_musd + undisbursed_commitment_musd, 2)                          AS exposure_affected_musd,
# MAGIC     round((past_due_disbursed_musd + watchlist_disbursed_musd) / nullif(current_disbursed_exposure_musd, 0), 3) AS distress_share,
# MAGIC     round(n_exited_at_loss / nullif(n_completed + n_exited_at_loss, 0), 3)                          AS closed_loss_rate
# MAGIC   FROM agg
# MAGIC ),
# MAGIC banded AS (
# MAGIC   SELECT *,
# MAGIC     round(0.4 * 100 * (6 - coalesce(exposure_weighted_risk_rating, avg_risk_rating_all)) / 5
# MAGIC         + 0.4 * 100 * (1 - coalesce(distress_share, 0))
# MAGIC         + 0.2 * 100 * (1 - coalesce(closed_loss_rate, 0)), 1)                                      AS health_score,
# MAGIC     CASE
# MAGIC       WHEN n_past_due >= 2 OR coalesce(distress_share, 0) >= 0.25 OR coalesce(exposure_weighted_risk_rating, 0) >= 4.5
# MAGIC         THEN 'REDUCE_OR_REVIEW'
# MAGIC       WHEN n_past_due = 0 AND n_watchlist = 0 AND coalesce(max_risk_rating_active, 9) <= 3
# MAGIC            AND coalesce(closed_loss_rate, 0) <= 0.05 AND n_active >= 3
# MAGIC         THEN 'CONTINUE'
# MAGIC       ELSE 'MONITOR'
# MAGIC     END                                                                                             AS band,
# MAGIC     concat_ws('; ',
# MAGIC       CASE WHEN n_past_due > 0 THEN concat(cast(n_past_due AS STRING), ' Past Due') END,
# MAGIC       CASE WHEN n_watchlist > 0 THEN concat(cast(n_watchlist AS STRING), ' Watchlist') END,
# MAGIC       CASE WHEN n_exited_at_loss > 0 THEN concat(cast(n_exited_at_loss AS STRING), ' exited at a loss') END,
# MAGIC       concat('exposure-weighted rating ', coalesce(cast(exposure_weighted_risk_rating AS STRING), 'n/a'), '/6'),
# MAGIC       concat(cast(round(100 * coalesce(distress_share, 0), 1) AS STRING), '% of current exposure distressed')
# MAGIC     )                                                                                               AS band_evidence
# MAGIC   FROM scored
# MAGIC )
# MAGIC SELECT *,
# MAGIC   rank() OVER (PARTITION BY band ORDER BY exposure_affected_musd DESC) AS materiality_rank_in_band
# MAGIC FROM banded;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Documentation in Unity Catalog — column comments from the data dictionary
# MAGIC Genie reads these comments to choose columns, and data stewards see them in Catalog Explorer.

# COMMAND ----------

GOLD_COMMENTS = {
    "project_url": "Unique project key (web address of the disclosure page). Join key between portfolio and monitoring (A01).",
    "project_number": "IFC project number. NOT unique: several projects share a number. Do not use as a key.",
    "project_name": "Name of the project.",
    "document_type": "Disclosure document type: Summary of Proposed Investment or Environmental & Social Review Summary.",
    "date_disclosed": "Date the project was publicly disclosed.",
    "product_line": "Principal IFC financing product recorded for the project: Loan, Equity, Guarantee or Risk Management.",
    "region": "Region (standardised to data-dictionary values; see region_as_reported and assumption A06).",
    "region_as_reported": "Region label exactly as in the source file.",
    "country": "Country in which the project is located.",
    "wb_country_code": "World Bank two-letter country code.",
    "industry": "Agribusiness, Energy, Finance, Manufacturing or Telecom.",
    "environmental_category": "Environmental & social risk category: A = potentially significant impact, B = limited, C = minimal.",
    "department": "IFC department responsible: CBA, CFG, FIG, INF or MAS.",
    "status": "Lifecycle status: Active (under way), Pending (not finalised), Closed (concluded), Dropped (cancelled).",
    "projected_board_date": "Date the project is scheduled to go to IFC's Board; may be in the future.",
    "approval_date": "Date IFC's Board approved the project; null if not yet approved.",
    "signed_date": "Date legal agreements were signed; null if not yet signed.",
    "invested_date": "Date of IFC's first disbursement; null if nothing disbursed.",
    "as_of_date": "Date the record was last updated.",
    "reporting_date": "Latest as_of_date in the data; anchor for 'last N years' questions (A02).",
    "loan_musd": "IFC investment allocated to loans, USD millions.",
    "equity_musd": "IFC investment allocated to equity, USD millions.",
    "guarantee_musd": "IFC investment allocated to guarantees, USD millions.",
    "risk_mgmt_musd": "IFC investment allocated to risk management products, USD millions.",
    "total_approved_musd": "Total IFC investment approved by the Board (proposed amount if not yet approved), USD millions.",
    "product_alloc_sum_musd": "Sum of the four product allocations, USD millions.",
    "alloc_gap_musd": "Board total minus sum of product allocations, USD millions (see Q28, A08).",
    "product_count": "Number of products with a non-zero allocation.",
    "is_multi_product": "True if more than one product has a non-zero allocation.",
    "is_board_approved": "True if approval_date is present (A04).",
    "is_committed": "True if signed and not Dropped (A05).",
    "is_monitored": "True if the project has a monitoring record (all non-Dropped projects).",
    "client_id": "Client identifier, e.g. CL-0087.",
    "client_name": "Client (company or institution IFC invests in or lends to).",
    "internal_risk_rating": "IFC internal credit rating, 1 = lowest risk to 6 = highest risk.",
    "disbursed_musd": "Amount IFC has paid out to date, USD millions; null for Pending projects.",
    "performance_status": "Performing, Watchlist, Past Due, Completed or Exited at a loss; null for Pending.",
    "days_since_last_review": "Days since last formal review; null for Closed projects.",
    "current_disbursed_exposure_musd": "Disbursed amount on Active projects, USD millions (A09).",
    "undisbursed_commitment_musd": "Approved but not yet disbursed and contractually committed, USD millions (A10).",
    "pipeline_unsigned_musd": "Approved or proposed amount on Pending projects not yet signed, USD millions.",
    "expected_credit_loss_musd": "60% of disbursed for Past Due projects, else 0, USD millions (A11).",
    "risk_flag": "RED = Past Due, AMBER = Watchlist, GREEN = Performing, CLOSED_OK, CLOSED_LOSS, NOT_APPLICABLE.",
    "is_new_renewable_generation": "Main purpose is new renewable generation capacity (text-derived, A13).",
    "new_capacity_mw": "New generation capacity in MW stated in the description; null if not stated (A13).",
    "is_msme_financing": "Main purpose is financing MSMEs (text-derived, A14).",
    "msme_target_group": "Main group of businesses targeted by MSME financing (text-derived).",
    "described_product": "Financing product named in the description (text-derived); compare with product_line for Q26.",
    "text_attributes_need_review": "True if LLM and rule extraction disagree and no reviewer has decided yet.",
}

def esc(s): return s.replace("'", "\\'")

for col, comment in GOLD_COMMENTS.items():
    spark.sql(f"ALTER TABLE gold_portfolio ALTER COLUMN {col} COMMENT '{esc(comment)}'")
try:
    for t, layer in [("bronze_projects", "bronze"), ("bronze_monitoring", "bronze"), ("silver_projects", "silver"),
                     ("silver_monitoring", "silver"), ("gold_portfolio", "gold"), ("gold_client_scorecard", "gold"),
                     ("gold_project_text_features", "gold")]:
        spark.sql(f"ALTER TABLE {t} SET TAGS ('layer' = '{layer}', 'domain' = 'cfo_portfolio', 'data_classification' = 'synthetic')")
except Exception as e:
    print(f"Tags not applied ({type(e).__name__}); comments are in place")
print(f"Documented {len(GOLD_COMMENTS)} gold_portfolio columns")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Data-quality checks — results are stored, not just displayed
# MAGIC `blocking` checks stop the pipeline. `warning` and `info` checks are recorded and explained in the README.
# MAGIC Expected control totals were computed independently from the source CSVs outside Databricks, which proves the
# MAGIC load is lossless.

# COMMAND ----------

import uuid
RUN_ID = str(uuid.uuid4())

CHECKS = [
    # (check_id, severity, description, SQL returning one number, expected, tolerance)
    ("B01", "blocking", "Bronze projects row count",                   "SELECT count(*) FROM bronze_projects", 5000, 0),
    ("B02", "blocking", "Bronze monitoring row count",                 "SELECT count(*) FROM bronze_monitoring", 3768, 0),
    ("B03", "blocking", "Control total: Board-approved (USD M)",       "SELECT round(sum(total_approved_musd), 2) FROM silver_projects", 742558.66, 0.05),
    ("B04", "blocking", "Control total: Loan (USD M)",                 "SELECT round(sum(loan_musd), 2) FROM silver_projects", 177612.77, 0.05),
    ("B05", "blocking", "Control total: Equity (USD M)",               "SELECT round(sum(equity_musd), 2) FROM silver_projects", 185967.90, 0.05),
    ("B06", "blocking", "Control total: Guarantee (USD M)",            "SELECT round(sum(guarantee_musd), 2) FROM silver_projects", 195285.29, 0.05),
    ("B07", "blocking", "Control total: Risk Management (USD M)",      "SELECT round(sum(risk_mgmt_musd), 2) FROM silver_projects", 184150.79, 0.05),
    ("B08", "blocking", "Control total: Disbursed (USD M)",            "SELECT round(sum(disbursed_musd), 2) FROM silver_monitoring", 296667.53, 0.05),
    ("K01", "blocking", "Project Url unique in portfolio",             "SELECT count(*) - count(DISTINCT project_url) FROM silver_projects", 0, 0),
    ("K02", "blocking", "Project Url unique in monitoring",            "SELECT count(*) - count(DISTINCT project_url) FROM silver_monitoring", 0, 0),
    ("K03", "blocking", "Monitoring rows without a portfolio project", "SELECT count(*) FROM silver_monitoring m LEFT ANTI JOIN silver_projects p USING (project_url)", 0, 0),
    ("K04", "blocking", "Project Number disagrees across tables for same URL",
        "SELECT count(*) FROM silver_monitoring m JOIN silver_projects p USING (project_url) WHERE m.project_number <> p.project_number", 0, 0),
    ("K05", "info",     "Distinct Project Numbers (proves it is not a key)", "SELECT count(DISTINCT project_number) FROM silver_projects", 3559, 0),
    ("K06", "blocking", "Client ID maps to exactly one client name",   "SELECT count(*) FROM (SELECT client_id FROM silver_monitoring GROUP BY client_id HAVING count(DISTINCT client_name) > 1)", 0, 0),
    ("S01", "blocking", "Dropped projects with a monitoring record",   "SELECT count(*) FROM gold_portfolio WHERE status = 'Dropped' AND is_monitored", 0, 0),
    ("S02", "blocking", "Non-Dropped projects without monitoring",     "SELECT count(*) FROM gold_portfolio WHERE status <> 'Dropped' AND NOT is_monitored", 0, 0),
    ("S03", "blocking", "Pending projects with performance or disbursement",
        "SELECT count(*) FROM gold_portfolio WHERE status = 'Pending' AND (performance_status IS NOT NULL OR disbursed_musd IS NOT NULL)", 0, 0),
    ("S04", "warning",  "Closed projects with days-since-review (dictionary says blank)",
        "SELECT count(*) FROM gold_portfolio WHERE status = 'Closed' AND days_since_last_review IS NOT NULL", 0, 0),
    ("S05", "blocking", "Disbursed exceeds approved",                  "SELECT count(*) FROM gold_portfolio WHERE disbursed_musd > total_approved_musd + 0.01", 0, 0),
    ("V01", "blocking", "Values outside data dictionary: product line", "SELECT count(*) FROM silver_projects WHERE product_line NOT IN ('Loan','Equity','Guarantee','Risk Management')", 0, 0),
    ("V02", "blocking", "Values outside data dictionary: region (after A06)",
        "SELECT count(*) FROM silver_projects WHERE region NOT IN ('East Asia & Pacific','Europe & Central Asia','Latin America','Middle East','North America','South Asia','Sub-Saharan Africa')", 0, 0),
    ("V03", "blocking", "Values outside data dictionary: status/category/department/industry",
        """SELECT count(*) FROM silver_projects WHERE status NOT IN ('Active','Pending','Closed','Dropped')
           OR environmental_category NOT IN ('A','B','C') OR department NOT IN ('CBA','CFG','FIG','INF','MAS')
           OR industry NOT IN ('Agribusiness','Energy','Finance','Manufacturing','Telecom')""", 0, 0),
    ("V04", "blocking", "Risk rating outside 1-6",                     "SELECT count_if(dq_risk_rating_out_of_range) FROM silver_monitoring", 0, 0),
    ("V05", "blocking", "Unparseable dates or amounts",
        """SELECT count(*) FROM bronze_projects b JOIN silver_projects s USING (project_url)
           WHERE (b.approval_date IS NOT NULL AND s.approval_date IS NULL) OR (b.signed_date IS NOT NULL AND s.signed_date IS NULL)
              OR (b.invested_date IS NOT NULL AND s.invested_date IS NULL) OR (b.total_approved_musd IS NOT NULL AND s.total_approved_musd IS NULL)""", 0, 0),
    ("D01", "info",     "Region labels restated (A06)",                "SELECT count_if(dq_region_restated) FROM silver_projects", 43, 0),
    ("D02", "info",     "Signed before Board approval (A07)",          "SELECT count_if(dq_signed_before_approval) FROM silver_projects", 37, 0),
    ("D03", "info",     "Invested but no signing date recorded",       "SELECT count_if(dq_invested_without_signing_date) FROM silver_projects", 16, 0),
    ("D04", "info",     "Board total differs from product allocations by > $1M (A08)", "SELECT count_if(dq_allocation_gap) FROM silver_projects", 146, 0),
    ("D05", "info",     "Records older than the reporting date (A17)", "SELECT count_if(dq_stale_snapshot) FROM silver_projects", None, None),
    ("D06", "info",     "Projects with an empty description (text attributes unavailable)",
        "SELECT count_if(coalesce(description_clean, '') = '') FROM silver_projects", 31, 0),
    ("T01", "warning",  "Text attributes awaiting human review (A12)", "SELECT count_if(needs_review) FROM gold_project_text_features", None, None),
    ("T02", "info",     "Rule-based: new renewable generation projects", "SELECT count_if(rb_is_new_renewable_generation) FROM rule_text_features", 277, 0),
    ("T03", "info",     "Rule-based: MSME financing projects",         "SELECT count_if(rb_is_msme_financing) FROM rule_text_features", None, None),
]

results = []
for cid, sev, desc, sql, expected, tol in CHECKS:
    actual = spark.sql(sql).collect()[0][0]
    actual = float(actual) if actual is not None else None
    passed = True if expected is None else (actual is not None and abs(actual - expected) <= tol)
    results.append((RUN_ID, cid, sev, desc, sql.strip(), None if expected is None else float(expected), actual, passed))

dq = spark.createDataFrame(results, "run_id STRING, check_id STRING, severity STRING, description STRING, check_sql STRING, expected DOUBLE, actual DOUBLE, passed BOOLEAN") \
          .withColumn("checked_at", F.current_timestamp())
spark.sql("""CREATE TABLE IF NOT EXISTS dq_results (run_id STRING, check_id STRING, severity STRING, description STRING,
             check_sql STRING, expected DOUBLE, actual DOUBLE, passed BOOLEAN, checked_at TIMESTAMP)
             COMMENT 'Every data-quality check, every run: expected vs actual'""")
dq.write.mode("append").saveAsTable("dq_results")
display(dq.orderBy("check_id"))

failed_blocking = [r for r in results if r[2] == "blocking" and not r[7]]
assert not failed_blocking, f"Blocking data-quality checks failed: {[(r[1], r[3], r[5], r[6]) for r in failed_blocking]}"
print(f"All blocking checks passed (run {RUN_ID})")

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Row-level issue log: which project, what issue. Analysts and the agent can cite it.
# MAGIC CREATE OR REPLACE TABLE dq_issue_log
# MAGIC COMMENT 'One row per project per data-quality issue; how each issue is treated is described in ref_assumptions'
# MAGIC AS
# MAGIC SELECT project_url, project_number, 'REGION_RESTATED' AS issue_code, concat(region_as_reported, ' -> ', region) AS detail, 'A06' AS assumption_id FROM silver_projects WHERE dq_region_restated
# MAGIC UNION ALL SELECT project_url, project_number, 'SIGNED_BEFORE_APPROVAL', concat('approved ', cast(approval_date AS STRING), ', signed ', cast(signed_date AS STRING)), 'A07' FROM silver_projects WHERE dq_signed_before_approval
# MAGIC UNION ALL SELECT project_url, project_number, 'INVESTED_WITHOUT_SIGNING_DATE', concat('invested ', cast(invested_date AS STRING)), 'A07' FROM silver_projects WHERE dq_invested_without_signing_date
# MAGIC UNION ALL SELECT project_url, project_number, 'ALLOCATION_GAP', concat('Board total minus allocations = ', cast(round(alloc_gap_musd, 2) AS STRING), ' USD M'), 'A08' FROM silver_projects WHERE dq_allocation_gap
# MAGIC UNION ALL SELECT project_url, project_number, 'STALE_SNAPSHOT', concat('as of ', cast(as_of_date AS STRING)), 'A17' FROM silver_projects WHERE dq_stale_snapshot
# MAGIC UNION ALL SELECT project_url, project_number, 'EMPTY_DESCRIPTION', 'No project description; text-derived attributes default to false', 'A12' FROM silver_projects WHERE coalesce(description_clean, '') = ''
# MAGIC UNION ALL SELECT t.project_url, p.project_number, 'TEXT_ATTRIBUTE_REVIEW', t.review_reason, 'A12' FROM gold_project_text_features t JOIN silver_projects p USING (project_url) WHERE t.needs_review;
# MAGIC
# MAGIC SELECT issue_code, assumption_id, count(*) AS projects FROM dq_issue_log GROUP BY ALL ORDER BY projects DESC;

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Sanity view
# MAGIC Status × monitoring coverage must show: Dropped → no monitoring; Pending → monitored but no performance or disbursement;
# MAGIC Active and Closed → complete.

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT status, count(*) AS projects, count_if(is_monitored) AS monitored,
# MAGIC        count(performance_status) AS with_performance, count(disbursed_musd) AS with_disbursement,
# MAGIC        round(sum(current_disbursed_exposure_musd), 1) AS current_exposure_musd,
# MAGIC        round(sum(undisbursed_commitment_musd), 1) AS undisbursed_commitment_musd
# MAGIC FROM gold_portfolio GROUP BY status ORDER BY projects DESC;
