# Databricks notebook source
# MAGIC %md
# MAGIC # WS1 — Certified answers to the 30 portfolio questions
# MAGIC
# MAGIC Every answer is produced with `answer(...)`, which displays the result **and** records in `answers_register`:
# MAGIC - the question, the **exact SQL**, the assumptions in words and their IDs in `ref_assumptions`;
# MAGIC - a result preview;
# MAGIC - where the status default matters (A03), the **same query excluding Dropped projects** and its result, as a
# MAGIC   sensitivity note (Q1, Q2, Q5, Q9, Q10, Q11, Q17, Q20);
# MAGIC - the answer's **scope** (which projects it covers) and, computed from it, how many of those projects carry open
# MAGIC   data-quality issues: the caveat that travels with the figure.
# MAGIC
# MAGIC All queries read **`certified_investment_portfolio`** only. Amounts are USD millions. These certified answers are the
# MAGIC ground truth for the Genie evaluation (same question, four phrasings).
# MAGIC
# MAGIC Run after the data pipeline (`01_data/00_reference` … `06_dq_checks`).

# COMMAND ----------

# MAGIC %run ../../00_setup/00_config

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT assumption_id, topic, statement FROM ref_assumptions ORDER BY assumption_id

# COMMAND ----------

# MAGIC %md
# MAGIC ## How the queries are written
# MAGIC Each query is a template. `{P}` is the certified table, `{REP}` the reporting date (A02) and `{SCOPE}` the status
# MAGIC default: `TRUE` for the certified answer (every status, A03) and `status <> 'Dropped'` for the sensitivity note. So the
# MAGIC sensitivity figure is the identical query with one extra condition, nothing else.

# COMMAND ----------

P = T("certified_investment_portfolio")
REP = f"(SELECT max(reporting_date) FROM {P})"
LAST_5_YEARS = f"approval_date > add_months({REP}, -60) AND approval_date <= {REP}"
INCLUDE_ALL, EXCLUDE_DROPPED = "TRUE", "status <> 'Dropped'"
Q28_THRESHOLD = Q28_ALLOCATION_THRESHOLD_MUSD
PRODUCTS = "('Loan', 'Equity', 'Guarantee', 'Risk Management')"


def fill(template: str, scope: str = INCLUDE_ALL) -> str:
    return template.format(P=P, REP=REP, LAST_5_YEARS=LAST_5_YEARS, SCOPE=scope, Q28=Q28_THRESHOLD)


def ws1(qid, question, template, assumptions, ids, scope_where, sensitivity=False):
    """Certified answer (all statuses); with sensitivity=True also the identical query excluding Dropped."""
    return answer(qid, question, fill(template), assumptions, assumption_ids=ids,
                  sensitivity_sql=fill(template, EXCLUDE_DROPPED) if sensitivity else None,
                  sensitivity_label="Excluding Dropped" if sensitivity else None,
                  scope_where=fill(scope_where))


# COMMAND ----------

# MAGIC %md
# MAGIC ## A. Investment amount analysis

# COMMAND ----------

ws1("Q01", "Show the total IFC loan investment by region for projects approved in the last 5 years.", """
SELECT region,
       count(*)                         AS projects_approved,
       round(sum(amt_loan_musd), 2)     AS loan_investment_musd
FROM {P}
WHERE {LAST_5_YEARS} AND {SCOPE}
GROUP BY region
ORDER BY loan_investment_musd DESC
""", "Last 5 years = approval date in (reporting date - 5 years, reporting date] = (2021-06-30, 2026-06-30] (A02). "
     "Loan = loan allocation column (A08). All statuses included (A03); sensitivity excludes Dropped.",
    "A02,A03,A08", "{LAST_5_YEARS}", sensitivity=True)

ws1("Q02", "List the top 10 projects by Total IFC investment as approved by the Board.", """
SELECT project_url, project_number, project_name, country, industry, status, approval_date,
       round(total_approved_musd, 2) AS total_approved_musd
FROM {P}
WHERE is_board_approved AND {SCOPE}
ORDER BY total_approved_musd DESC
LIMIT 10
""", "Only Board-approved projects (approval date present); for unapproved projects the column is a proposal (A04). "
     "All statuses (A03); sensitivity excludes Dropped.",
    "A03,A04,A08", "project_url IN (SELECT project_url FROM (SELECT project_url, total_approved_musd AS t FROM {P} WHERE is_board_approved "
                   "ORDER BY t DESC LIMIT 10))",
    sensitivity=True)

ws1("Q03", "Compare Equity vs Loan investment across industries, excluding Dropped projects.", """
SELECT industry,
       round(sum(amt_equity_musd), 2) AS equity_musd,
       round(sum(amt_loan_musd), 2)   AS loan_musd,
       round(sum(amt_equity_musd) / nullif(sum(amt_equity_musd) + sum(amt_loan_musd), 0) * 100, 1) AS equity_share_of_equity_plus_loan_pct
FROM {P}
WHERE status <> 'Dropped'
GROUP BY industry
ORDER BY industry
""", "Product allocation columns (A08). Dropped excluded as the question states.",
    "A08", "status <> 'Dropped'")

ws1("Q04", "Which countries received more than $1,000M of IFC loan investment across their Active and Closed projects?", """
SELECT country, count(*) AS projects, round(sum(amt_loan_musd), 2) AS loan_investment_musd
FROM {P}
WHERE status IN ('Active', 'Closed')
GROUP BY country
HAVING sum(amt_loan_musd) > 1000
ORDER BY loan_investment_musd DESC
""", "Loan allocation column (A08); threshold is strictly greater than 1,000 USD M.",
    "A08", "status IN ('Active', 'Closed') AND country IN (SELECT country FROM (SELECT country, sum(amt_loan_musd) AS loan "
           "FROM {P} WHERE status IN ('Active', 'Closed') GROUP BY country) WHERE loan > 1000)")

ws1("Q05", "Show the trend of IFC approved investment year-over-year.", """
WITH y AS (
  SELECT approval_year, count(*) AS projects_approved, sum(total_approved_musd) AS approved_musd
  FROM {P}
  WHERE is_board_approved AND {SCOPE}
  GROUP BY approval_year
)
SELECT approval_year, projects_approved, round(approved_musd, 2) AS approved_musd,
       round((approved_musd / lag(approved_musd) OVER (ORDER BY approval_year) - 1) * 100, 1) AS yoy_change_pct
FROM y ORDER BY approval_year
""", "Calendar year of Board approval; approved amount = Board total (A04, A08). The final year is partial (data to "
     "2026-06-30). All statuses (A03); sensitivity excludes Dropped.",
    "A02,A03,A04,A08", "is_board_approved", sensitivity=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## B. Country & region insights

# COMMAND ----------

ws1("Q06", "What are the top performing regions by committed investment? Treat a project as committed once its agreements are signed, unless it was later Dropped.", """
SELECT region, count(*) AS committed_projects,
       round(sum(total_approved_musd), 2) AS committed_investment_musd,
       rank() OVER (ORDER BY sum(total_approved_musd) DESC) AS rank
FROM {P}
WHERE is_committed
GROUP BY region
ORDER BY committed_investment_musd DESC
""", "Committed = signed date present and status not Dropped (A05). Amount = Board total (A08). Regions standardized (A06).",
    "A05,A06,A08", "is_committed")

ws1("Q07", "List the 10 countries with the highest number of Active projects.", """
SELECT country, count(*) AS active_projects
FROM {P}
WHERE status = 'Active'
GROUP BY country
ORDER BY active_projects DESC, country
LIMIT 10
""", "Projects counted by project_url (A01). Ties at rank 10 are broken alphabetically.",
    "A01", "status = 'Active' AND country IN (SELECT country FROM (SELECT country, count(*) AS n FROM {P} "
           "WHERE status = 'Active' GROUP BY country ORDER BY n DESC, country LIMIT 10))")

ws1("Q08", "Show the IFC investment split (Loan / Equity / Guarantee / Risk Management) for East Asia & Pacific, excluding Dropped projects.", """
SELECT product, round(amount_musd, 2) AS amount_musd,
       round(amount_musd / sum(amount_musd) OVER () * 100, 1) AS share_pct
FROM (
  SELECT stack(4, 'Loan', l, 'Equity', e, 'Guarantee', g, 'Risk Management', r) AS (product, amount_musd)
  FROM (
    SELECT sum(amt_loan_musd) AS l, sum(amt_equity_musd) AS e, sum(amt_guarantee_musd) AS g, sum(amt_risk_mgmt_musd) AS r
    FROM {P}
    WHERE region = 'East Asia & Pacific' AND status <> 'Dropped'
  )
)
ORDER BY amount_musd DESC
""", "Product allocation columns (A08). Dropped excluded as the question states.",
    "A08", "region = 'East Asia & Pacific' AND status <> 'Dropped'")

ws1("Q09", "Which 10 WB Country Codes have the longest average time between approval and signing? Only include codes with at least 10 signed projects.", """
SELECT wb_country_code, any_value(country) AS country,
       count(*) AS signed_projects,
       round(avg(days_approval_to_signing), 1) AS avg_days_approval_to_signing
FROM {P}
WHERE days_approval_to_signing IS NOT NULL AND {SCOPE}
GROUP BY wb_country_code
HAVING count(*) >= 10
ORDER BY avg_days_approval_to_signing DESC
LIMIT 10
""", "Signed projects with both dates in valid order; projects signed before approval are excluded from the average and "
     "from the count of 10 (A07). All statuses (A03); sensitivity excludes Dropped.",
    "A03,A07", "days_approval_to_signing IS NOT NULL AND wb_country_code IN (SELECT wb_country_code FROM ("
               "SELECT wb_country_code, count(*) AS n, avg(days_approval_to_signing) AS avg_days FROM {P} "
               "WHERE days_approval_to_signing IS NOT NULL GROUP BY wb_country_code) WHERE n >= 10 "
               "ORDER BY avg_days DESC LIMIT 10)", sensitivity=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Timeline & progress monitoring

# COMMAND ----------

ws1("Q10", "For each industry, show the number of projects approved and the number first invested each year from 2020 to 2025.", """
WITH a AS (SELECT industry, approval_year AS yr, count(*) AS n FROM {P}
           WHERE approval_year BETWEEN 2020 AND 2025 AND {SCOPE} GROUP BY ALL),
     i AS (SELECT industry, invested_year AS yr, count(*) AS n FROM {P}
           WHERE invested_year BETWEEN 2020 AND 2025 AND {SCOPE} GROUP BY ALL)
SELECT coalesce(a.industry, i.industry) AS industry, coalesce(a.yr, i.yr) AS year,
       coalesce(a.n, 0) AS projects_approved, coalesce(i.n, 0) AS projects_first_invested
FROM a FULL OUTER JOIN i ON a.industry = i.industry AND a.yr = i.yr
ORDER BY industry, year
""", "Approved counted by calendar year of approval; first invested counted by calendar year of the invested date "
     "(first disbursement). All statuses (A03); sensitivity excludes Dropped.",
    "A03", "approval_year BETWEEN 2020 AND 2025 OR invested_year BETWEEN 2020 AND 2025", sensitivity=True)

ws1("Q11", "Show the average time taken between Approval -> Signing -> Investment for each region.", """
SELECT region,
       round(avg(days_approval_to_signing), 1)    AS avg_days_approval_to_signing,
       round(avg(days_signing_to_investment), 1)  AS avg_days_signing_to_investment,
       round(avg(days_approval_to_investment), 1) AS avg_days_approval_to_investment,
       count(days_approval_to_signing)            AS n_approval_to_signing,
       count(days_signing_to_investment)          AS n_signing_to_investment
FROM {P}
WHERE {SCOPE}
GROUP BY region
ORDER BY avg_days_approval_to_investment DESC
""", "Each interval averages the projects that have both dates in valid order (A07), so the counts per interval differ. "
     "All statuses (A03); sensitivity excludes Dropped.",
    "A03,A06,A07", "days_approval_to_signing IS NOT NULL OR days_signing_to_investment IS NOT NULL", sensitivity=True)

ws1("Q12", "List Pending projects whose Projected Board Date has passed as of their As of Date but that have not yet been approved.", """
SELECT project_url, project_number, project_name, country, industry, projected_board_date, as_of_date,
       datediff(as_of_date, projected_board_date) AS days_overdue,
       round(total_approved_musd, 2) AS proposed_musd
FROM {P}
WHERE status = 'Pending' AND approval_date IS NULL
  AND projected_board_date < as_of_date
ORDER BY days_overdue DESC, project_url
""", "Compared against each record's own As of Date, as the question specifies; same rule as flag board_date_passed (A19). "
     "Amount is the proposed amount (A04).",
    "A04,A19", "status = 'Pending' AND approval_date IS NULL AND projected_board_date < as_of_date")

# COMMAND ----------

# MAGIC %md
# MAGIC ## D. Document & project-level queries

# COMMAND ----------

ws1("Q13", "[Challenge] Which Active projects have new renewable power generation as their main purpose? Show the count and approved amount by region.", """
SELECT coalesce(region, 'TOTAL') AS region_label, count(*) AS projects,
       round(sum(total_approved_musd), 2) AS approved_musd,
       count_if(text_attributes_need_review) AS awaiting_review
FROM {P}
WHERE status = 'Active' AND is_new_renewable_generation
GROUP BY ROLLUP(region)
ORDER BY region_label = 'TOTAL', approved_musd DESC
""", "Main purpose classified from the description by LLM cross-checked with rules (A12, A13): excludes transmission and "
     "distribution, standalone storage, gas plants, rooftop solar for own use, and lending programmes that merely mention renewables.",
    "A12,A13", "status = 'Active' AND is_new_renewable_generation")

ws1("Q13_detail", "[Challenge] Q13 project list", """
SELECT project_url, project_number, project_name, region, country, round(total_approved_musd, 2) AS approved_musd,
       new_capacity_mw, text_attributes_need_review, description_clean
FROM {P} WHERE status = 'Active' AND is_new_renewable_generation
ORDER BY region, approved_musd DESC
""", "Evidence for Q13.", "A12,A13", "status = 'Active' AND is_new_renewable_generation")

ws1("Q14", "How many Summary of Proposed Investment documents were disclosed each year after 2020?", """
SELECT disclosed_year AS year_disclosed, count(*) AS spi_documents
FROM {P}
WHERE document_type = 'Summary of Proposed Investment' AND disclosed_year > 2020
GROUP BY disclosed_year ORDER BY year_disclosed
""", "After 2020 = calendar year 2021 onwards. One document per project row. All statuses (A03).",
    "A03", "document_type = 'Summary of Proposed Investment' AND disclosed_year > 2020")

ws1("Q15", "Which projects have an Environmental Category = A but are still Pending? Show the count and approved amount by region.", """
SELECT coalesce(region, 'TOTAL') AS region_label, count(*) AS projects,
       round(sum(total_approved_musd), 2) AS approved_or_proposed_musd
FROM {P}
WHERE environmental_category = 'A' AND status = 'Pending'
GROUP BY ROLLUP(region)
ORDER BY region_label = 'TOTAL', approved_or_proposed_musd DESC
""", "For Pending projects not yet approved the amount is the proposed amount (A04).",
    "A04", "environmental_category = 'A' AND status = 'Pending'")

ws1("Q15_detail", "Q15 project list", """
SELECT region, project_url, project_number, project_name, country, approval_date, round(total_approved_musd, 2) AS approved_or_proposed_musd
FROM {P}
WHERE environmental_category = 'A' AND status = 'Pending'
ORDER BY region, approved_or_proposed_musd DESC
""", "Evidence for Q15.", "A04", "environmental_category = 'A' AND status = 'Pending'")

ws1("Q16", "Find all projects with Document Type = Environmental & Social Review Summary, broken down by Environmental Category.", """
SELECT environmental_category, count(*) AS projects, round(sum(total_approved_musd), 2) AS total_musd
FROM {P}
WHERE document_type = 'Environmental & Social Review Summary'
GROUP BY environmental_category ORDER BY environmental_category
""", "All statuses (A03). Full project list in Q16_detail.",
    "A03", "document_type = 'Environmental & Social Review Summary'")

ws1("Q16_detail", "Q16 project list", """
SELECT environmental_category, project_url, project_number, project_name, country, status, round(total_approved_musd, 2) AS total_musd
FROM {P}
WHERE document_type = 'Environmental & Social Review Summary'
ORDER BY environmental_category, total_musd DESC
""", "Evidence for Q16.", "A03", "document_type = 'Environmental & Social Review Summary'")

# COMMAND ----------

# MAGIC %md
# MAGIC ## E. Department & product line insights

# COMMAND ----------

ws1("Q17", "Show approved investment by Department for projects approved in the last 5 years.", """
SELECT department, count(*) AS projects_approved, round(sum(total_approved_musd), 2) AS approved_musd
FROM {P}
WHERE {LAST_5_YEARS} AND {SCOPE}
GROUP BY department ORDER BY approved_musd DESC
""", "Same 5-year window as Q01 (A02). Approved = Board total (A08). All statuses (A03); sensitivity excludes Dropped.",
    "A02,A03,A08", "{LAST_5_YEARS}", sensitivity=True)

ws1("Q18", "Compare Product Line categories (Loan, Equity, Guarantee, Risk Management) across regions, excluding Dropped projects.", """
SELECT region,
       round(sum(amt_loan_musd), 2)       AS loan_musd,
       round(sum(amt_equity_musd), 2)     AS equity_musd,
       round(sum(amt_guarantee_musd), 2)  AS guarantee_musd,
       round(sum(amt_risk_mgmt_musd), 2)  AS risk_management_musd,
       count_if(product_line = 'Loan') AS n_loan_principal, count_if(product_line = 'Equity') AS n_equity_principal,
       count_if(product_line = 'Guarantee') AS n_guarantee_principal, count_if(product_line = 'Risk Management') AS n_rm_principal
FROM {P}
WHERE status <> 'Dropped'
GROUP BY region ORDER BY region
""", "Amounts from the allocation columns; counts by recorded principal Product Line (A08). Dropped excluded as the question states.",
    "A06,A08", "status <> 'Dropped'")

ws1("Q19", "Which industries receive the largest risk management investments, and what share of each industry's investment is risk management?", """
SELECT industry,
       round(sum(amt_risk_mgmt_musd), 2) AS risk_management_musd,
       round(sum(product_alloc_sum_musd), 2) AS total_allocated_musd,
       round(sum(amt_risk_mgmt_musd) / sum(product_alloc_sum_musd) * 100, 1) AS risk_management_share_pct
FROM {P}
GROUP BY industry ORDER BY risk_management_musd DESC
""", "Share = risk management allocation / sum of all four allocations, so numerator and denominator are on the same "
     "basis (A08). All statuses (A03).",
    "A03,A08", "TRUE")

ws1("Q20", "Show the number of projects approved by each Department yearly from 2020 to 2025.", """
SELECT * FROM (
  SELECT department, approval_year AS yr FROM {P}
  WHERE approval_year BETWEEN 2020 AND 2025 AND {SCOPE}
) PIVOT (count(1) FOR yr IN (2020, 2021, 2022, 2023, 2024, 2025))
ORDER BY department
""", "Counted by calendar year of approval. All statuses (A03); sensitivity excludes Dropped.",
    "A03", "approval_year BETWEEN 2020 AND 2025", sensitivity=True)

# COMMAND ----------

# MAGIC %md
# MAGIC ## F. Status & risk-based queries

# COMMAND ----------

ws1("Q21", "Find all Dropped projects with more than $250M originally approved investment.", """
SELECT project_url, project_number, project_name, country, industry, approval_date,
       is_board_approved AS was_board_approved, round(total_approved_musd, 2) AS total_musd
FROM {P}
WHERE status = 'Dropped' AND total_approved_musd > 250
ORDER BY was_board_approved DESC, total_musd DESC
""", "Lists every Dropped project whose Total exceeds $250M and shows whether the Board had approved it. Strictly "
     "'originally approved' = was_board_approved = true; the others were dropped before approval and their amount was only "
     "proposed (A04).",
    "A04", "status = 'Dropped' AND total_approved_musd > 250")

ws1("Q22", "List all Active projects whose first investment came more than 2 years after Board approval.", """
SELECT project_url, project_number, project_name, country, approval_date, invested_date,
       days_approval_to_investment, round(days_approval_to_investment / 365.25, 2) AS years_to_first_investment
FROM {P}
WHERE status = 'Active' AND invested_date > add_months(approval_date, 24)
ORDER BY days_approval_to_investment DESC
""", "More than 2 years = invested date later than approval date + 24 months (A07: valid sequences only).",
    "A07", "status = 'Active' AND invested_date > add_months(approval_date, 24)")

ws1("Q23", "What percentage of projects are Active, Closed, Pending, and Dropped in each region?", """
SELECT * FROM (
  SELECT region, status, round(count(*) * 100.0 / sum(count(*)) OVER (PARTITION BY region), 1) AS pct
  FROM {P} GROUP BY region, status
) PIVOT (first(pct) FOR status IN ('Active', 'Closed', 'Pending', 'Dropped'))
ORDER BY region
""", "Share of project count within each region (rows sum to 100% up to rounding). Regions standardized (A06).",
    "A01,A06", "TRUE")

# COMMAND ----------

# MAGIC %md
# MAGIC ## G. Text & semantic search queries ([Challenge])

# COMMAND ----------

ws1("Q24", "[Challenge] What is the total new renewable generation capacity (MW) of Active and Closed projects, by region, and how many of these projects do not state a capacity?", """
SELECT coalesce(region, 'TOTAL') AS region_label,
       count(*) AS renewable_generation_projects,
       round(sum(new_capacity_mw), 1) AS total_new_capacity_mw,
       count_if(new_capacity_mw IS NULL) AS projects_without_stated_capacity,
       count_if(text_attributes_need_review) AS awaiting_review
FROM {P}
WHERE status IN ('Active', 'Closed') AND is_new_renewable_generation
GROUP BY ROLLUP(region)
ORDER BY region_label = 'TOTAL', total_new_capacity_mw DESC
""", "Capacity = new MW added by the project (GW converted x1000; expansions count only the added MW; MWh of storage ignored). "
     "MW of other sponsors' plants connected by a transmission line are not counted (A13).",
    "A12,A13", "status IN ('Active', 'Closed') AND is_new_renewable_generation")

ws1("Q25a", "[Challenge] MSME financing (excluding Dropped): number of projects and approved amount", """
SELECT count(*) AS msme_projects, round(sum(total_approved_musd), 2) AS approved_musd,
       count(DISTINCT country) AS countries, count(DISTINCT client_id) AS clients,
       count_if(text_attributes_need_review) AS awaiting_review
FROM {P}
WHERE status <> 'Dropped' AND is_msme_financing
""", "MSME financing = main purpose is financing micro, small or medium enterprises; excludes SMEs as suppliers or "
     "incidental beneficiaries, explicit exclusions and household microloans (A14).",
    "A12,A14", "status <> 'Dropped' AND is_msme_financing")

ws1("Q25b", "[Challenge] MSME financing: top 5 countries", """
SELECT country, count(*) AS msme_projects, round(sum(total_approved_musd), 2) AS approved_musd
FROM {P}
WHERE status <> 'Dropped' AND is_msme_financing
GROUP BY country ORDER BY approved_musd DESC LIMIT 5
""", "Ranked by approved amount.", "A12,A14", "status <> 'Dropped' AND is_msme_financing")

ws1("Q25c", "[Challenge] MSME financing: main groups of businesses targeted", """
SELECT msme_target_group, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 1) AS share_of_projects_pct
FROM {P}
WHERE status <> 'Dropped' AND is_msme_financing
GROUP BY msme_target_group ORDER BY projects DESC
""", "Target group extracted from the description (A12).", "A12,A14", "status <> 'Dropped' AND is_msme_financing")

ws1("Q26a", "[Challenge] Which projects' descriptions describe a different financing product than the one recorded in Product Line? Count by recorded Product Line.", """
SELECT product_line AS recorded_product_line, described_product, count(*) AS projects
FROM {P}
WHERE described_product IS NOT NULL AND described_product <> product_line
GROUP BY ALL ORDER BY recorded_product_line, projects DESC
""", "Described product = principal instrument named in the text (e.g. 'interest rate swap' = Risk Management; 'X alongside "
     "a smaller Y' = X). Projects whose description names no instrument are excluded (A12).",
    "A12", "described_product IS NOT NULL AND described_product <> product_line")

ws1("Q26b", "[Challenge] Q26 project list", """
SELECT project_url, project_number, project_name, product_line AS recorded_product_line, described_product,
       round(amt_loan_musd, 2) AS loan_musd, round(amt_equity_musd, 2) AS equity_musd,
       round(amt_guarantee_musd, 2) AS guarantee_musd, round(amt_risk_mgmt_musd, 2) AS risk_mgmt_musd,
       text_attributes_need_review, description_clean
FROM {P}
WHERE described_product IS NOT NULL AND described_product <> product_line
ORDER BY recorded_product_line, project_number, project_url
""", "Allocation columns are shown so a reviewer can see which record is likely wrong.",
    "A08,A12", "described_product IS NOT NULL AND described_product <> product_line")

# COMMAND ----------

# MAGIC %md
# MAGIC ## H. Complex multi-metric analysis

# COMMAND ----------

q27 = ws1("Q27", "Bubble chart for the 15 countries with the highest approved investment (excluding Dropped): x = Loan, y = Equity, size = Total.", """
SELECT country, round(sum(amt_loan_musd), 2) AS loan_musd, round(sum(amt_equity_musd), 2) AS equity_musd,
       round(sum(total_approved_musd), 2) AS total_approved_musd
FROM {P} WHERE status <> 'Dropped'
GROUP BY country ORDER BY total_approved_musd DESC LIMIT 15
""", "Size = Board total; x and y = allocation columns (A08). Dropped excluded as the question states.",
    "A08", "status <> 'Dropped' AND country IN (SELECT country FROM (SELECT country, sum(total_approved_musd) AS total "
           "FROM {P} WHERE status <> 'Dropped' GROUP BY country ORDER BY total DESC LIMIT 15))")

try:
    import plotly.express as px
    fig = px.scatter(q27.toPandas(), x="loan_musd", y="equity_musd", size="total_approved_musd", text="country",
                     title="Top 15 countries by approved investment (excl. Dropped), USD M",
                     labels={"loan_musd": "Loan investment (USD M)", "equity_musd": "Equity investment (USD M)"})
    fig.update_traces(textposition="top center")
    fig.show()
except ImportError:
    print("plotly not available - use the notebook chart editor on the Q27 table (Scatter, size = total_approved_musd)")

# COMMAND ----------

ws1("Q28", "Which projects have a Board-approved total that differs from the sum of their product allocations by more than $1M?", """
SELECT project_url, project_number, project_name, status, round(total_approved_musd, 2) AS board_total_musd,
       round(product_alloc_sum_musd, 2) AS sum_of_allocations_musd, round(alloc_gap_musd, 2) AS difference_musd
FROM {P}
WHERE abs(alloc_gap_musd) > {Q28}
ORDER BY abs(alloc_gap_musd) DESC, project_url
""", "Absolute difference greater than $1M, computed from the gap itself, not from the $0.01M allocation flags (A08). "
     "Data-quality finding: reported, not corrected.",
    "A08", "abs(alloc_gap_musd) > {Q28}")

ws1("Q29", "List multi-product projects (more than one product with a non-zero allocation) and their totals.", """
SELECT project_url, project_number, project_name, product_line AS principal_product, product_count,
       round(amt_loan_musd, 2) AS loan_musd, round(amt_equity_musd, 2) AS equity_musd,
       round(amt_guarantee_musd, 2) AS guarantee_musd, round(amt_risk_mgmt_musd, 2) AS risk_mgmt_musd,
       round(total_approved_musd, 2) AS total_musd
FROM {P} WHERE is_multi_product
ORDER BY total_musd DESC, project_url
""", "Multi-product = more than one allocation column above zero (A08). All statuses (A03).",
    "A03,A08", "is_multi_product")

q30 = ws1("Q30", "Heatmap of region vs industry based on total approved investment, excluding Dropped projects.", """
SELECT * FROM (
  SELECT region, industry, total_approved_musd AS amt FROM {P} WHERE status <> 'Dropped'
) PIVOT (round(sum(amt), 2) FOR industry IN ('Agribusiness', 'Energy', 'Finance', 'Manufacturing', 'Telecom'))
ORDER BY region
""", "Approved = Board total (A08). Regions standardized (A06). Dropped excluded as the question states.",
    "A06,A08", "status <> 'Dropped'")

try:
    import plotly.express as px
    h = q30.toPandas().set_index("region")
    px.imshow(h, text_auto=True, aspect="auto", color_continuous_scale="Purples",
              title="Approved investment by region and industry (excl. Dropped), USD M").show()
except ImportError:
    print("plotly not available - use the notebook chart editor (Heatmap) on the Q30 table")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Reconciliation: the answers agree with each other and with the data
# MAGIC Independent cross-checks; each prints OK or FAIL and is stored in `ops_dq_checks` (ids `W..`). Any FAIL stops the
# MAGIC notebook **before** the answers are saved.

# COMMAND ----------

def ans(qid):
    """The exact SQL recorded for an answer in this run."""
    return next(a for a in _ANSWERS if a["question_id"] == qid)["sql_text"]


RECON = [
    ("W01", "Q01 regional loan totals sum to the portfolio loan total for the same 5-year window",
     f"SELECT sum(loan_investment_musd) FROM ({ans('Q01')})",
     f"SELECT round(sum(amt_loan_musd), 2) FROM {P} WHERE {LAST_5_YEARS}", 0.05),
    ("W02", "Q06 regional committed totals sum to the committed total",
     f"SELECT sum(committed_investment_musd) FROM ({ans('Q06')})",
     f"SELECT round(sum(total_approved_musd), 2) FROM {P} WHERE is_committed", 0.05),
    ("W03", "Q08 product split for East Asia & Pacific sums to the allocation total (excl. Dropped)",
     f"SELECT round(sum(amt_loan_musd + amt_equity_musd + amt_guarantee_musd + amt_risk_mgmt_musd), 2) FROM {P} WHERE region = 'East Asia & Pacific' AND status <> 'Dropped'",
     f"SELECT round(sum(product_alloc_sum_musd), 2) FROM {P} WHERE region = 'East Asia & Pacific' AND status <> 'Dropped'", 0.05),
    ("W04", "Q18 product columns across regions sum to the portfolio product totals (excl. Dropped)",
     f"SELECT round(sum(loan_musd + equity_musd + guarantee_musd + risk_management_musd), 2) FROM ({ans('Q18')})",
     f"SELECT round(sum(product_alloc_sum_musd), 2) FROM {P} WHERE status <> 'Dropped'", 0.1),
    ("W05", "Q18 principal product counts sum to the non-Dropped project count",
     f"SELECT sum(n_loan_principal + n_equity_principal + n_guarantee_principal + n_rm_principal) FROM ({ans('Q18')})",
     f"SELECT count(*) FROM {P} WHERE status <> 'Dropped' AND product_line IN {PRODUCTS}", 0),
    ("W06", "Q23 status percentages sum to 100 in every region (largest deviation from 100, rounding allowed)",
     f"SELECT max(abs(coalesce(Active, 0) + coalesce(Closed, 0) + coalesce(Pending, 0) + coalesce(Dropped, 0) - 100)) FROM ({ans('Q23')})",
     "SELECT 0", 0.2),
    ("W07", "Q12 list = projects carrying flag_board_date_passed",
     f"SELECT count(*) FROM ({ans('Q12')})",
     f"SELECT count_if(flag_board_date_passed) FROM {P}", 0),
    ("W08", "Q13 TOTAL row = sum of its regions",
     f"SELECT sum(CASE WHEN region_label = 'TOTAL' THEN approved_musd ELSE -approved_musd END) FROM ({ans('Q13')})",
     "SELECT 0", 0.05),
    ("W09", "Q13 summary count = Q13 detail list",
     f"SELECT max(projects) FROM ({ans('Q13')}) WHERE region_label = 'TOTAL'",
     f"SELECT count(*) FROM ({ans('Q13_detail')})", 0),
    ("W10", "Q24 TOTAL capacity = sum of its regions",
     f"SELECT sum(CASE WHEN region_label = 'TOTAL' THEN total_new_capacity_mw ELSE -total_new_capacity_mw END) FROM ({ans('Q24')})",
     "SELECT 0", 0.5),
    ("W11", "Q26a counts = Q26b list",
     f"SELECT sum(projects) FROM ({ans('Q26a')})",
     f"SELECT count(*) FROM ({ans('Q26b')})", 0),
    ("W12", "Q28 count = projects with an allocation gap above the Q28 threshold (independent of the flags)",
     f"SELECT count(*) FROM ({ans('Q28')})",
     f"SELECT count(*) FROM {P} WHERE abs(total_approved_musd - (amt_loan_musd + amt_equity_musd + amt_guarantee_musd + amt_risk_mgmt_musd)) > {Q28_THRESHOLD}", 0),
    ("W13", "Q30 heatmap sums to the approved total excluding Dropped",
     f"SELECT round(sum(coalesce(Agribusiness, 0) + coalesce(Energy, 0) + coalesce(Finance, 0) + coalesce(Manufacturing, 0) + coalesce(Telecom, 0)), 2) FROM ({ans('Q30')})",
     f"SELECT round(sum(total_approved_musd), 2) FROM {P} WHERE status <> 'Dropped'", 0.5),
    ("W14", "Q16 summary count = Q16 detail list",
     f"SELECT sum(projects) FROM ({ans('Q16')})",
     f"SELECT count(*) FROM ({ans('Q16_detail')})", 0),
]


def scalar(sql):
    v = spark.sql(sql).collect()[0][0]
    return float(v) if v is not None else None


import uuid  # noqa: E402

RECON_RUN = str(uuid.uuid4())
recon_rows = []
for cid, desc, actual_sql, expected_sql, tol in RECON:
    actual, expected = scalar(actual_sql), scalar(expected_sql)
    ok = actual is not None and expected is not None and abs(actual - expected) <= tol
    recon_rows.append((RECON_RUN, cid, "blocking", "WS1 reconciliation: " + desc, actual_sql, expected_sql, expected, actual, float(tol), ok))
    print(f"[{'OK  ' if ok else 'FAIL'}] {cid} {desc}: {actual} vs {expected}")

from pyspark.sql import functions as F  # noqa: E402

spark.createDataFrame(recon_rows, "run_id STRING, check_id STRING, severity STRING, description STRING, check_sql STRING, "
                                  "expected_sql STRING, expected DOUBLE, actual DOUBLE, tolerance DOUBLE, passed BOOLEAN") \
    .withColumn("checked_at", F.current_timestamp()).write.mode("append").saveAsTable(T("ops_dq_checks"))
failed = [r[1] for r in recon_rows if not r[9]]
if failed:
    raise RuntimeError(f"WS1 reconciliation failed: {failed}. Answers were NOT saved.")
print(f"All {len(recon_rows)} reconciliation checks passed.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Save the certified answers
# MAGIC This workstream's rows in `answers_register` are replaced; WS2 and WS3 rows are not touched.

# COMMAND ----------

persist_answers("WS1")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT question_id, row_count, assumption_ids, sensitivity_label, rows_in_scope, rows_needing_review,
# MAGIC        rows_high_severity, rows_text_review, left(question, 90) AS question
# MAGIC FROM answers_register WHERE workstream = 'WS1' ORDER BY question_id
