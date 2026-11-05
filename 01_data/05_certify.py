# Databricks notebook source
# MAGIC %md
# MAGIC # 05_certify — the certified investment portfolio
# MAGIC
# MAGIC Builds **`certified_investment_portfolio`**: one row per IFC project, the single table that every WS1 answer, Genie and
# MAGIC the evaluation read. "Certified" means every row has passed the schema gate and validation, every data-quality
# MAGIC issue travels with the row as a flag, and every definition is written down in `ref_assumptions`.
# MAGIC
# MAGIC ```
# MAGIC validated_projects ─┐
# MAGIC validated_monitoring ┼─(LEFT JOIN on project_url, A01)─► certified_investment_portfolio
# MAGIC enriched_project_text_features ┘
# MAGIC ```
# MAGIC
# MAGIC | Column group | Content |
# MAGIC |---|---|
# MAGIC | Project record | Every validated project column (contract names, e.g. `amt_loan_musd`), plus `region_as_reported` |
# MAGIC | Derived amounts | `product_alloc_sum_musd`, `alloc_gap_musd`, `product_count`, `is_multi_product` (A08) |
# MAGIC | Lifecycle | `is_board_approved`, `is_signed`, `is_invested`, `is_committed`; day intervals for valid sequences only (A07); calendar and IFC fiscal years (Jul–Jun, labelled by the June year) |
# MAGIC | Monitoring | client, risk rating, disbursed, performance, days since last review, `is_climate_related` |
# MAGIC | Exposure | current disbursed exposure, undisbursed commitment, unsigned pipeline, expected credit loss (A09–A11), `risk_flag` |
# MAGIC | Text attributes | new renewable generation, MW, MSME financing, target group, described product (A12–A14), `text_attributes_need_review` |
# MAGIC | Data quality | every project `flag_*`, every monitoring flag as `mon_flag_*`, and combined roll-ups: `needs_review`, `dq_max_severity`, `review_owners`, `dq_messages`, `dq_flag_ids`, `dq_flag_count` |
# MAGIC
# MAGIC Flag columns are generated from the data contracts, so a rule added to a contract appears here automatically.
# MAGIC Column comments (read by Genie) are written at the end.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from ifc_common import load_contracts  # noqa: E402

CONTRACTS = load_contracts(CFG["_contracts_dir"])
PROJECT_FLAGS = CONTRACTS["projects"].get("flag_rules", [])
MONITORING_FLAGS = CONTRACTS["monitoring"].get("flag_rules", [])
TARGET = T("certified_investment_portfolio")

# COMMAND ----------

# MAGIC %md ## Build the table

# COMMAND ----------


def year_cols(date_col: str, prefix: str) -> list:
    """Calendar year and IFC fiscal year (July-June, labelled by the June year)."""
    return [f"year(p.{date_col}) AS {prefix}_year",
            f"year(p.{date_col}) + CASE WHEN month(p.{date_col}) >= 7 THEN 1 ELSE 0 END AS {prefix}_fy"]


ALLOC_SUM = "(p.amt_loan_musd + p.amt_equity_musd + p.amt_guarantee_musd + p.amt_risk_mgmt_musd)"
SEVERITY_RANK = "CASE {c} WHEN 'high' THEN 3 WHEN 'warning' THEN 2 WHEN 'info' THEN 1 ELSE 0 END"

select_cols = [
    # --- project record
    "p.project_url", "p.project_number", "p.project_name", "p.document_type", "p.date_disclosed",
    "p.product_line", "p.region", "p.region_as_reported", "p.country", "p.wb_country_code", "p.industry",
    "p.environmental_category", "p.department", "p.status",
    "p.projected_board_date", "p.approval_date", "p.signed_date", "p.invested_date", "p.as_of_date",
    "max(p.as_of_date) OVER () AS reporting_date",
    "p.amt_loan_musd", "p.amt_equity_musd", "p.amt_guarantee_musd", "p.amt_risk_mgmt_musd", "p.total_approved_musd",
    # --- derived amounts (A08)
    f"{ALLOC_SUM} AS product_alloc_sum_musd",
    f"p.total_approved_musd - {ALLOC_SUM} AS alloc_gap_musd",
    "(CASE WHEN p.amt_loan_musd > 0 THEN 1 ELSE 0 END + CASE WHEN p.amt_equity_musd > 0 THEN 1 ELSE 0 END"
    " + CASE WHEN p.amt_guarantee_musd > 0 THEN 1 ELSE 0 END + CASE WHEN p.amt_risk_mgmt_musd > 0 THEN 1 ELSE 0 END) AS product_count",
    "(CASE WHEN p.amt_loan_musd > 0 THEN 1 ELSE 0 END + CASE WHEN p.amt_equity_musd > 0 THEN 1 ELSE 0 END"
    " + CASE WHEN p.amt_guarantee_musd > 0 THEN 1 ELSE 0 END + CASE WHEN p.amt_risk_mgmt_musd > 0 THEN 1 ELSE 0 END) > 1 AS is_multi_product",
    # --- lifecycle (A04, A05, A07)
    "p.approval_date IS NOT NULL AS is_board_approved",
    "p.signed_date IS NOT NULL AS is_signed",
    "p.invested_date IS NOT NULL AS is_invested",
    "p.signed_date IS NOT NULL AND p.status <> 'Dropped' AS is_committed",
    "CASE WHEN p.signed_date >= p.approval_date THEN datediff(p.signed_date, p.approval_date) END AS days_approval_to_signing",
    "CASE WHEN p.invested_date >= p.signed_date THEN datediff(p.invested_date, p.signed_date) END AS days_signing_to_investment",
    "CASE WHEN p.invested_date >= p.approval_date THEN datediff(p.invested_date, p.approval_date) END AS days_approval_to_investment",
    *year_cols("approval_date", "approval"), *year_cols("signed_date", "signed"),
    *year_cols("invested_date", "invested"), *year_cols("date_disclosed", "disclosed"),
    # --- monitoring
    "m.project_url IS NOT NULL AS is_monitored",
    "m.client_id", "m.client_name", "m.internal_risk_rating", "m.currency", "m.climate_flag", "m.is_climate_related",
    "m.disbursed_musd", "m.performance_status", "m.days_since_last_review",
    # --- exposure (A09, A10, A11)
    "CASE WHEN p.status = 'Active' THEN coalesce(m.disbursed_musd, 0) ELSE 0 END AS current_disbursed_exposure_musd",
    "CASE WHEN p.status = 'Active' THEN greatest(p.total_approved_musd - coalesce(m.disbursed_musd, 0), 0)"
    " WHEN p.status = 'Pending' AND p.signed_date IS NOT NULL THEN p.total_approved_musd ELSE 0 END AS undisbursed_commitment_musd",
    "CASE WHEN p.status = 'Pending' AND p.signed_date IS NULL THEN p.total_approved_musd ELSE 0 END AS pipeline_unsigned_musd",
    f"CASE WHEN m.performance_status = 'Past Due' THEN {ECL_LOSS_RATE} * coalesce(m.disbursed_musd, 0) ELSE 0 END AS expected_credit_loss_musd",
    "CASE m.performance_status WHEN 'Past Due' THEN 'RED' WHEN 'Watchlist' THEN 'AMBER' WHEN 'Performing' THEN 'GREEN'"
    " WHEN 'Completed' THEN 'CLOSED_OK' WHEN 'Exited at a loss' THEN 'CLOSED_LOSS' ELSE 'NOT_APPLICABLE' END AS risk_flag",
    # --- text attributes (A12-A14)
    "tf.is_new_renewable_generation", "tf.new_capacity_mw", "tf.is_msme_financing", "tf.msme_target_group",
    "tf.described_product", "coalesce(tf.needs_review, false) AS text_attributes_need_review", "tf.review_reason AS text_review_reason",
    "p.project_description", "trim(regexp_replace(p.project_description, '\\\\s+', ' ')) AS description_clean",
    # --- data quality: every flag, then combined roll-ups (project OR monitoring)
    *[f"p.flag_{r['name']}" for r in PROJECT_FLAGS],
    *[f"coalesce(m.flag_{r['name']}, false) AS mon_flag_{r['name']}" for r in MONITORING_FLAGS],
    "coalesce(p.needs_review, false) OR coalesce(m.needs_review, false) AS needs_review",
    "CASE greatest(" + SEVERITY_RANK.format(c="p.dq_max_severity") + ", " + SEVERITY_RANK.format(c="m.dq_max_severity")
    + ") WHEN 3 THEN 'high' WHEN 2 THEN 'warning' WHEN 1 THEN 'info' ELSE 'none' END AS dq_max_severity",
    "array_join(array_sort(array_distinct(filter(concat(split(coalesce(p.review_owners, ''), ', '),"
    " split(coalesce(m.review_owners, ''), ', ')), x -> x <> ''))), ', ') AS review_owners",
    "concat_ws(' | ', nullif(p.dq_messages, ''), nullif(m.dq_messages, '')) AS dq_messages",
    "concat_ws(',', nullif(p.dq_flag_ids, ''), nullif(m.dq_flag_ids, '')) AS dq_flag_ids",
    "coalesce(p.dq_flag_count, 0) + coalesce(m.dq_flag_count, 0) AS dq_flag_count",
    # --- lineage
    "p._source_file AS _projects_source_file", "m._source_file AS _monitoring_source_file",
    "p._contract_version AS _projects_contract_version", "p._validation_run_id",
]

BUILD_SQL = (f"CREATE OR REPLACE TABLE {TARGET}\n"
             "COMMENT 'Certified investment portfolio: one row per IFC project (portfolio + monitoring + text attributes + every "
             "data-quality flag). The table every WS1 answer and Genie read. Amounts in USD millions. Definitions in ref_assumptions.'\n"
             "AS SELECT\n  " + ",\n  ".join(select_cols) + "\n"
             f"FROM {T('validated_projects')} p\n"
             f"LEFT JOIN {T('validated_monitoring')} m ON p.project_url = m.project_url\n"
             f"LEFT JOIN {T('enriched_project_text_features')} tf ON p.project_url = tf.project_url")
spark.sql(BUILD_SQL)
print(f"Built {TARGET}: {spark.table(TARGET).count()} rows, {len(spark.table(TARGET).columns)} columns")

# COMMAND ----------

# MAGIC %md ## Column comments (Genie reads these to choose columns)

# COMMAND ----------

COMMENTS = {
    "project_url": "Unique project key (web address of the disclosure page). Join key between portfolio and monitoring; count projects by this column (A01).",
    "project_number": "IFC project number. NOT unique: several projects share a number. Never use it to count or join projects.",
    "project_name": "Name of the project. Names repeat across projects.",
    "document_type": "Disclosure document type: Summary of Proposed Investment or Environmental & Social Review Summary.",
    "date_disclosed": "Date the project was publicly disclosed.",
    "product_line": "Principal IFC financing product recorded for the project: Loan, Equity, Guarantee or Risk Management.",
    "region": "Region, standardized to the data-dictionary values (A06). Middle East includes North Africa; Latin America includes the Caribbean. For sub-regions filter on country.",
    "region_as_reported": "Region label exactly as in the source file, before standardization.",
    "country": "Country in which the project is located.",
    "wb_country_code": "World Bank two-letter country code.",
    "industry": "Agribusiness, Energy, Finance, Manufacturing or Telecom.",
    "environmental_category": "Environmental & social risk category: A = potentially significant impact, B = limited, C = minimal.",
    "department": "IFC department responsible: CBA, CFG, FIG, INF or MAS.",
    "status": "Lifecycle status: Active (under way), Pending (not finalised), Closed (concluded), Dropped (cancelled). Filter on status only when a question asks for it (A03).",
    "projected_board_date": "Date the project is scheduled to go to IFC's Board; may be in the future.",
    "approval_date": "Date IFC's Board approved the project; null if not yet approved (A04).",
    "signed_date": "Date legal agreements were signed; null if not yet signed.",
    "invested_date": "Date of IFC's first disbursement; null if nothing disbursed.",
    "as_of_date": "Date the record was last updated.",
    "reporting_date": "Latest as_of_date in the data (2026-06-30 on the first delivery). Anchor for 'last N years' questions instead of today's date (A02).",
    "amt_loan_musd": "IFC investment allocated to loans, USD millions. Use for product mix only, not totals (A08).",
    "amt_equity_musd": "IFC investment allocated to equity, USD millions. Use for product mix only, not totals (A08).",
    "amt_guarantee_musd": "IFC investment allocated to guarantees, USD millions. Use for product mix only, not totals (A08).",
    "amt_risk_mgmt_musd": "IFC investment allocated to risk management products, USD millions. Use for product mix only, not totals (A08).",
    "total_approved_musd": "Total IFC investment approved by the Board (proposed amount if not yet approved), USD millions. Use for all totals (A08).",
    "product_alloc_sum_musd": "Sum of the four product allocations, USD millions.",
    "alloc_gap_musd": "Board total minus sum of product allocations, USD millions. Q28 lists projects with abs(alloc_gap_musd) > 1 (A08).",
    "product_count": "Number of products with a non-zero allocation.",
    "is_multi_product": "True if more than one product has a non-zero allocation.",
    "is_board_approved": "True if approval_date is present (A04).",
    "is_signed": "True if signed_date is present.",
    "is_invested": "True if invested_date is present (first disbursement made).",
    "is_committed": "True if signed and not Dropped (A05).",
    "days_approval_to_signing": "Days from Board approval to signing; null when signing is before approval (A07).",
    "days_signing_to_investment": "Days from signing to first disbursement; null for invalid sequences (A07).",
    "days_approval_to_investment": "Days from Board approval to first disbursement; null for invalid sequences (A07).",
    "approval_year": "Calendar year of approval_date.",
    "approval_fy": "IFC fiscal year of approval_date (July-June, labelled by the June year: 2025-07-01 is FY2026).",
    "signed_year": "Calendar year of signed_date.",
    "signed_fy": "IFC fiscal year of signed_date (July-June, labelled by the June year).",
    "invested_year": "Calendar year of invested_date.",
    "invested_fy": "IFC fiscal year of invested_date (July-June, labelled by the June year).",
    "disclosed_year": "Calendar year of date_disclosed.",
    "disclosed_fy": "IFC fiscal year of date_disclosed (July-June, labelled by the June year).",
    "is_monitored": "True if the project has a monitoring record (every non-Dropped project).",
    "client_id": "Client identifier, e.g. CL-0087.",
    "client_name": "Client (company or institution IFC invests in or lends to).",
    "internal_risk_rating": "IFC internal credit rating, 1 = lowest risk to 6 = highest risk.",
    "currency": "Currency of the investment (informational; all amounts are USD millions, A16).",
    "climate_flag": "Yes/No as supplied by the monitoring team.",
    "is_climate_related": "True when climate_flag = 'Yes'.",
    "disbursed_musd": "Amount IFC has paid out to date, USD millions; null for Pending projects. Use for exposure, not totals.",
    "performance_status": "Performing, Watchlist, Past Due, Completed or Exited at a loss; null for Pending.",
    "days_since_last_review": "Days since last formal review as of as_of_date; null for Closed projects.",
    "current_disbursed_exposure_musd": "Disbursed amount on Active projects, USD millions (A09).",
    "undisbursed_commitment_musd": "Approved but not yet disbursed and contractually committed, USD millions (A10).",
    "pipeline_unsigned_musd": "Approved or proposed amount on Pending projects not yet signed, USD millions.",
    "expected_credit_loss_musd": f"{ECL_LOSS_RATE:.0%} of disbursed for Past Due projects, else 0, USD millions (A11).",
    "risk_flag": "RED = Past Due, AMBER = Watchlist, GREEN = Performing, CLOSED_OK, CLOSED_LOSS, NOT_APPLICABLE.",
    "is_new_renewable_generation": "Main purpose is new renewable generation capacity (text-derived, A13).",
    "new_capacity_mw": "New generation capacity in MW stated in the description; null if not stated (A13).",
    "is_msme_financing": "Main purpose is financing MSMEs (text-derived, A14).",
    "msme_target_group": "Main group of businesses targeted by MSME financing (text-derived).",
    "described_product": "Financing product named in the description (text-derived); compare with product_line for Q26.",
    "text_attributes_need_review": "True if LLM and rule extraction disagree (or the LLM result is missing) and no reviewer has decided yet (A12).",
    "text_review_reason": "Why the text attributes need review: renewable, capacity, msme or product disagreement, llm_missing, or no_description.",
    "project_description": "Free-text project description as supplied (31 are blank).",
    "description_clean": "project_description with whitespace normalized.",
    "needs_review": "True if the project or its monitoring record has a warning or high-severity data-quality flag. Report how many rows in an answer have this set.",
    "dq_max_severity": "Worst data-quality severity on the project or its monitoring record: high, warning, info or none.",
    "review_owners": "Teams that should act on the open warning/high flags, comma-separated.",
    "dq_messages": "Plain-English description of every data-quality flag on the row.",
    "dq_flag_ids": "IDs of the flag rules hit (P-F.. for projects, M-F.. for monitoring), comma-separated.",
    "dq_flag_count": "Number of data-quality flags on the project and its monitoring record.",
    "_projects_source_file": "Source file the project row was loaded from (lineage).",
    "_monitoring_source_file": "Source file the monitoring row was loaded from (lineage).",
    "_projects_contract_version": "Version of the projects data contract the row was validated against.",
    "_validation_run_id": "ID of the validation run that produced the project row.",
}
for r in PROJECT_FLAGS:
    COMMENTS[f"flag_{r['name']}"] = f"Data-quality flag {r['id']} ({r['severity']}, owner: {r['owner']}): {r['description']}."
for r in MONITORING_FLAGS:
    COMMENTS[f"mon_flag_{r['name']}"] = (f"Monitoring data-quality flag {r['id']} ({r['severity']}, owner: {r['owner']}): "
                                         f"{r['description']}. False for projects without a monitoring record.")


def esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


columns = set(spark.table(TARGET).columns)
missing = sorted(columns - set(COMMENTS))
for col, comment in COMMENTS.items():
    if col in columns:
        spark.sql(f"ALTER TABLE {TARGET} ALTER COLUMN {col} COMMENT '{esc(comment)}'")
print(f"Documented {len(columns) - len(missing)} of {len(columns)} columns" + (f"; no comment for {missing}" if missing else ""))

# COMMAND ----------

# MAGIC %md ## Layer tags (visible in Catalog Explorer)

# COMMAND ----------

LAYER_TAGS = [
    ("raw_projects", "raw"), ("raw_monitoring", "raw"),
    ("validated_projects", "validated"), ("validated_monitoring", "validated"),
    ("enriched_rule_features", "enriched"), ("enriched_llm_extractions", "enriched"),
    ("enriched_project_text_features", "enriched"),
    ("certified_investment_portfolio", "certified"),
    ("ref_assumptions", "reference"), ("ref_region_mapping", "reference"), ("ref_product_vocabulary", "reference"),
]
for name, layer in LAYER_TAGS:
    try:
        spark.sql(f"ALTER TABLE {T(name)} SET TAGS ('layer' = '{layer}', 'domain' = 'cfo_portfolio', 'data_classification' = 'synthetic')")
    except Exception as e:
        print(f"Tags not applied to {name} ({type(e).__name__}); comments are in place")

# COMMAND ----------

# MAGIC %md ## Check

# COMMAND ----------

display(spark.sql(f"""
  SELECT count(*) AS projects, count(DISTINCT project_url) AS distinct_urls,
         count_if(is_monitored) AS monitored,
         count_if(status = 'Closed') AS closed, count_if(status = 'Active') AS active,
         count_if(status = 'Pending') AS pending, count_if(status = 'Dropped') AS dropped,
         count_if(mon_flag_review_overdue) AS review_overdue,
         count_if(flag_board_date_passed) AS board_date_passed,
         count_if(abs(alloc_gap_musd) > {Q28_ALLOCATION_THRESHOLD_MUSD}) AS q28_gap_projects,
         count_if(needs_review) AS needs_review, count_if(dq_max_severity = 'high') AS high_severity,
         count_if(text_attributes_need_review) AS text_needs_review,
         round(sum(total_approved_musd), 2) AS total_approved_musd
  FROM {TARGET}"""))  # noqa: F821
