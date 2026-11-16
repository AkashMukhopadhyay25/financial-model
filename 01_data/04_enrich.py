# Databricks notebook source
# MAGIC %md
# MAGIC # 04_enrich — facts that exist only in the project descriptions
# MAGIC
# MAGIC The four [Challenge] questions (13, 24, 25, 26) need facts that are only in free text: new renewable generation and its
# MAGIC capacity in MW, MSME financing and its target group, and the financing instrument the text names.
# MAGIC
# MAGIC Two independent methods, then reconciliation (assumption A12):
# MAGIC 1. **Deterministic rules** (regex on the description's first sentence plus `ref_product_vocabulary`). Fast, free,
# MAGIC    explainable, but brittle. → `enriched_rule_features`
# MAGIC 2. **LLM extraction** with `ai_query` and a strict JSON contract. Handles negations (*"rather than SMEs"*), transmission
# MAGIC    lines that connect *other sponsors'* farms, GW→MW, expansions. → `enriched_llm_extractions` (cached audit trail)
# MAGIC 3. **Reconcile:** a reviewer override (`ref_text_feature_overrides`) wins, then the LLM, then the rule. Any disagreement
# MAGIC    sets `needs_review = true` with a `review_reason`. → `enriched_project_text_features`
# MAGIC
# MAGIC **Cost control.** The LLM sees a description only once: results are cached by (`project_url`, `sha2(description_clean)`),
# MAGIC so only new or changed descriptions are sent. Results already cached in another schema (`ai.legacy_llm_cache_table`, optional) are
# MAGIC copied in once. `ai.llm_extraction_limit` in the config caps calls per run (5 for smoke tests); a full run needs explicit
# MAGIC approval. Extraction runs **once in the pipeline**, not at question time, so every user gets the same answer.
# MAGIC
# MAGIC Reads `validated_projects` (Stage 3). Run after `03_validate`.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

# MAGIC %md ## Input: validated projects with a whitespace-normalized description
# MAGIC `description_clean` must stay computed exactly this way: it is part of the LLM cache key.

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TEMPORARY VIEW enrich_base AS
SELECT project_url, industry, project_description,
       trim(regexp_replace(project_description, '\\\\s+', ' '))                AS description_clean,
       sha2(trim(regexp_replace(project_description, '\\\\s+', ' ')), 256)     AS description_hash
FROM {T('validated_projects')}
""")
display(spark.sql("SELECT count(*) AS projects, count_if(coalesce(description_clean, '') <> '') AS with_description FROM enrich_base"))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 1. Deterministic rules → `enriched_rule_features`

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE enriched_rule_features
# MAGIC COMMENT 'Deterministic (regex/vocabulary) extraction of text attributes from project descriptions; baseline used to cross-check the LLM (assumption A12)'
# MAGIC AS
# MAGIC WITH base AS (
# MAGIC   SELECT project_url, industry, description_clean AS d,
# MAGIC          coalesce(description_clean, '') <> '' AS has_description,
# MAGIC          -- first sentence; the look-behind stops "S.A." in company names from ending the sentence
# MAGIC          coalesce(nullif(regexp_extract(description_clean, '^(.*?(?<!S\\.A)\\.)(\\s|$)', 1), ''), description_clean) AS s1
# MAGIC   FROM enrich_base
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

# MAGIC %md ## 2. LLM extraction → `enriched_llm_extractions` (cached, incremental)
# MAGIC The table is an audit trail: model, timestamp and raw response are stored. It is **never replaced or emptied**.

# COMMAND ----------

LLM_TABLE = T("enriched_llm_extractions")
LEGACY_LLM_TABLE = CFG["ai"].get("legacy_llm_cache_table")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {LLM_TABLE} (
  project_url STRING, description_hash STRING, model_endpoint STRING, extracted_at TIMESTAMP,
  raw_response STRING, error_message STRING,
  is_new_renewable_generation BOOLEAN, new_capacity_mw DOUBLE, is_msme_financing BOOLEAN,
  msme_target_group STRING, described_product STRING)
COMMENT 'Audit trail of LLM extraction from project descriptions (one row per project per description version). Never replaced: it is the LLM cache.'
""")

# Optional copy of results cached in another schema, so those descriptions are never sent to the model again.
# Only rows not already present are inserted, so re-running this cell changes nothing.
# A bare name is looked up in this schema; a full catalog.schema.table name (e.g. the team schema's cache, when this
# pipeline runs in a separate schema) is used as given. Read-only: the source table is never changed.
LEGACY_FQN = (LEGACY_LLM_TABLE if LEGACY_LLM_TABLE and "." in LEGACY_LLM_TABLE else T(LEGACY_LLM_TABLE)) \
    if LEGACY_LLM_TABLE else None
if LEGACY_FQN and LEGACY_FQN != LLM_TABLE and spark.catalog.tableExists(LEGACY_FQN):
    before = spark.table(LLM_TABLE).count()
    spark.sql(f"""
    INSERT INTO {LLM_TABLE}
    SELECT s.project_url, s.description_hash, s.model_endpoint, s.extracted_at, s.raw_response, s.error_message,
           s.is_new_renewable_generation, s.new_capacity_mw, s.is_msme_financing, s.msme_target_group, s.described_product
    FROM {LEGACY_FQN} s
    LEFT ANTI JOIN {LLM_TABLE} e
      ON e.project_url = s.project_url AND e.description_hash = s.description_hash AND e.extracted_at = s.extracted_at
    """)
    print(f"Copied {spark.table(LLM_TABLE).count() - before} cached rows from {LEGACY_FQN}.")
else:
    print("No shared LLM cache configured.")

# COMMAND ----------

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


pending = []
if RUN_LLM_EXTRACTION:
    # Descriptions not yet extracted successfully (new, changed, or failed/unparseable last time).
    todo = spark.sql(f"""
      SELECT b.project_url, b.description_clean, b.description_hash
      FROM enrich_base b
      LEFT ANTI JOIN (SELECT * FROM {LLM_TABLE}
                      WHERE error_message IS NULL AND is_new_renewable_generation IS NOT NULL) e
        ON e.project_url = b.project_url AND e.description_hash = b.description_hash
      WHERE coalesce(b.description_clean, '') <> ''   -- blank descriptions: nothing to extract
      ORDER BY b.project_url""")
    n_todo = todo.count()
    if LLM_EXTRACTION_LIMIT:
        todo = todo.limit(int(LLM_EXTRACTION_LIMIT))
    pending = todo.collect()   # at most 5,000 short rows
    print(f"{n_todo} descriptions not yet extracted; sending {len(pending)} this run "
          f"(limit {LLM_EXTRACTION_LIMIT}) in batches of {LLM_BATCH_SIZE}, {LLM_PARALLELISM} parallel calls")
else:
    print("ai.run_llm_extraction = false: no model calls; text features without a cached LLM result come from rules "
          "only and are flagged for review")

# Small inputs land in a single Spark partition, which makes ai_query call the model one row at a time.
# Repartitioning each batch runs LLM_PARALLELISM calls concurrently; committing per batch saves progress.
for start in range(0, len(pending), LLM_BATCH_SIZE):
    spark.createDataFrame(pending[start:start + LLM_BATCH_SIZE], schema=todo.schema) \
         .repartition(LLM_PARALLELISM).createOrReplaceTempView("llm_todo_batch")
    spark.sql(f"""
    INSERT INTO {LLM_TABLE}
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

display(spark.sql(f"""
  SELECT count(*) AS extractions, count(DISTINCT project_url) AS projects,
         count_if(error_message IS NOT NULL) AS model_errors,
         count_if(error_message IS NULL AND is_new_renewable_generation IS NULL) AS unparseable
  FROM {LLM_TABLE}"""))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## 3. Reconcile → `enriched_project_text_features`
# MAGIC Reviewer override > LLM > rule. `needs_review` = the two methods disagree, or the LLM result is missing, and no
# MAGIC reviewer has decided yet. These rows feed `text_attributes_need_review` in `certified_investment_portfolio`.

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE enriched_project_text_features
# MAGIC COMMENT 'Text-derived project attributes: reviewer override > LLM > rule. needs_review flags disagreement or missing LLM output (assumption A12)'
# MAGIC AS
# MAGIC WITH llm AS (
# MAGIC   SELECT * FROM (
# MAGIC     SELECT e.*, row_number() OVER (PARTITION BY e.project_url ORDER BY e.extracted_at DESC) AS rn
# MAGIC     FROM enriched_llm_extractions e
# MAGIC     JOIN enrich_base b ON b.project_url = e.project_url AND e.description_hash = b.description_hash
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
# MAGIC   FROM enriched_rule_features r
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

# MAGIC %md ## Check

# COMMAND ----------

display(spark.sql("""
  SELECT count(*)                                          AS projects,
         count_if(rb_is_new_renewable_generation)          AS rule_new_renewable,   -- 277 on the first delivery (check T02)
         count_if(is_new_renewable_generation)             AS final_new_renewable,
         round(sum(new_capacity_mw), 1)                    AS final_new_capacity_mw,
         count_if(is_msme_financing)                       AS final_msme_financing,
         count_if(needs_review)                            AS needs_review,
         count_if(has_reviewer_override)                   AS reviewer_overrides,
         count_if(llm_renew IS NULL AND review_reason <> 'no_description') AS llm_missing
  FROM enriched_project_text_features"""))  # noqa: F821
display(spark.sql("""
  SELECT coalesce(review_reason, 'agree') AS review_reason, count(*) AS projects, count_if(needs_review) AS needs_review
  FROM enriched_project_text_features GROUP BY ALL ORDER BY projects DESC"""))  # noqa: F821
