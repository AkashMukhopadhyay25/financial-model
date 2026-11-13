# Databricks notebook source
# MAGIC %md
# MAGIC # WS1 — Baseline analytics: answers to the 30 portfolio questions
# MAGIC
# MAGIC Every answer is produced with `answer(question_id, question, sql, assumptions)`, which displays the result **and**
# MAGIC records the question, the exact SQL, the assumptions and a result preview in `answers_register`.
# MAGIC These answers also become the **benchmark set for Genie and the agent** (see `02_agent/02_agent_capabilities`).
# MAGIC
# MAGIC All queries read the governed table `gold_portfolio` (built in `01_data/01_load_and_prepare`).
# MAGIC Global assumptions are in `ref_assumptions` (A01–A17). Question-specific interpretation is stated next to each answer.
# MAGIC Amounts are USD millions.

# COMMAND ----------

# MAGIC %run ../../00_setup/00_config

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT assumption_id, topic, statement FROM ref_assumptions ORDER BY assumption_id

# COMMAND ----------

# MAGIC %md
# MAGIC ## A. Investment amount analysis

# COMMAND ----------

answer("Q01", "Show the total IFC loan investment by region for projects approved in the last 5 years.", """
SELECT region,
       count(*)                     AS projects_approved,
       round(sum(loan_musd), 2)     AS loan_investment_musd
FROM gold_portfolio
WHERE approval_date >  add_months((SELECT max(reporting_date) FROM gold_portfolio), -60)
  AND approval_date <= (SELECT max(reporting_date) FROM gold_portfolio)
GROUP BY region
ORDER BY loan_investment_musd DESC
""", "Last 5 years = approval date in (2021-06-30, 2026-06-30] relative to the reporting date (A02). Loan = loan allocation column (A08). All statuses included (A03).")

answer("Q02", "List the top 10 projects by Total IFC investment as approved by the Board.", """
SELECT project_number, project_name, country, industry, status, approval_date,
       round(total_approved_musd, 2) AS total_approved_musd
FROM gold_portfolio
WHERE is_board_approved
ORDER BY total_approved_musd DESC
LIMIT 10
""", "Only Board-approved projects (approval date present); for unapproved projects the column is a proposal (A04).")

answer("Q03", "Compare Equity vs Loan investment across industries, excluding Dropped projects.", """
SELECT industry,
       round(sum(equity_musd), 2) AS equity_musd,
       round(sum(loan_musd), 2)   AS loan_musd,
       round(sum(equity_musd) / nullif(sum(equity_musd) + sum(loan_musd), 0) * 100, 1) AS equity_share_of_equity_plus_loan_pct
FROM gold_portfolio
WHERE status <> 'Dropped'
GROUP BY industry
ORDER BY industry
""", "Product allocation columns (A08).")

answer("Q04", "Which countries received more than $1,000M of IFC loan investment across their Active and Closed projects?", """
SELECT country, count(*) AS projects, round(sum(loan_musd), 2) AS loan_investment_musd
FROM gold_portfolio
WHERE status IN ('Active', 'Closed')
GROUP BY country
HAVING sum(loan_musd) > 1000
ORDER BY loan_investment_musd DESC
""", "Loan allocation column; threshold is strictly greater than 1,000 USD M.")

answer("Q05", "Show the trend of IFC approved investment year-over-year.", """
WITH y AS (
  SELECT year(approval_date) AS approval_year, count(*) AS projects_approved,
         sum(total_approved_musd) AS approved_musd
  FROM gold_portfolio
  WHERE is_board_approved
  GROUP BY year(approval_date)
)
SELECT approval_year, projects_approved, round(approved_musd, 2) AS approved_musd,
       round((approved_musd / lag(approved_musd) OVER (ORDER BY approval_year) - 1) * 100, 1) AS yoy_change_pct
FROM y ORDER BY approval_year
""", "Year of Board approval; approved amount = Board total (A04). The final year may be partial (data to 2026-06-30).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## B. Country & region insights

# COMMAND ----------

answer("Q06", "What are the top performing regions by committed investment? Treat a project as committed once its agreements are signed, unless it was later Dropped.", """
SELECT region, count(*) AS committed_projects,
       round(sum(total_approved_musd), 2) AS committed_investment_musd,
       rank() OVER (ORDER BY sum(total_approved_musd) DESC) AS rank
FROM gold_portfolio
WHERE is_committed
GROUP BY region
ORDER BY committed_investment_musd DESC
""", "Committed = signed date present and status not Dropped (A05). Amount = Board total.")

answer("Q07", "List the 10 countries with the highest number of Active projects.", """
SELECT country, count(*) AS active_projects
FROM gold_portfolio
WHERE status = 'Active'
GROUP BY country
ORDER BY active_projects DESC, country
LIMIT 10
""", "Ties at rank 10 are broken alphabetically; check the next rows if the count at rank 10 is shared.")

answer("Q08", "Show the IFC investment split (Loan / Equity / Guarantee / Risk Management) for East Asia & Pacific, excluding Dropped projects.", """
SELECT product, round(amount_musd, 2) AS amount_musd,
       round(amount_musd / sum(amount_musd) OVER () * 100, 1) AS share_pct
FROM (
  SELECT stack(4, 'Loan', l, 'Equity', e, 'Guarantee', g, 'Risk Management', r) AS (product, amount_musd)
  FROM (
    SELECT sum(loan_musd) AS l, sum(equity_musd) AS e, sum(guarantee_musd) AS g, sum(risk_mgmt_musd) AS r
    FROM gold_portfolio
    WHERE region = 'East Asia & Pacific' AND status <> 'Dropped'
  )
)
ORDER BY amount_musd DESC
""", "Product allocation columns (A08).")

answer("Q09", "Which 10 WB Country Codes have the longest average time between approval and signing? Only include codes with at least 10 signed projects.", """
SELECT wb_country_code, any_value(country) AS country,
       count(*) AS signed_projects,
       round(avg(days_approval_to_signing), 1) AS avg_days_approval_to_signing
FROM gold_portfolio
WHERE days_approval_to_signing IS NOT NULL
GROUP BY wb_country_code
HAVING count(*) >= 10
ORDER BY avg_days_approval_to_signing DESC
LIMIT 10
""", "Signed projects with both dates in valid order; the 37 signed-before-approval records are excluded (A07). All statuses (A03).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## C. Timeline & progress monitoring

# COMMAND ----------

answer("Q10", "For each industry, show the number of projects approved and the number first invested each year from 2020 to 2025.", """
WITH a AS (SELECT industry, year(approval_date) AS yr, count(*) AS n FROM gold_portfolio
           WHERE year(approval_date) BETWEEN 2020 AND 2025 GROUP BY ALL),
     i AS (SELECT industry, year(invested_date) AS yr, count(*) AS n FROM gold_portfolio
           WHERE year(invested_date) BETWEEN 2020 AND 2025 GROUP BY ALL)
SELECT coalesce(a.industry, i.industry) AS industry, coalesce(a.yr, i.yr) AS year,
       coalesce(a.n, 0) AS projects_approved, coalesce(i.n, 0) AS projects_first_invested
FROM a FULL OUTER JOIN i ON a.industry = i.industry AND a.yr = i.yr
ORDER BY industry, year
""", "Approved counted by approval year; first invested counted by invested-date year (date of first disbursement). All statuses (A03).")

answer("Q11", "Show the average time taken between Approval -> Signing -> Investment for each region.", """
SELECT region,
       round(avg(days_approval_to_signing), 1)    AS avg_days_approval_to_signing,
       round(avg(days_signing_to_investment), 1)  AS avg_days_signing_to_investment,
       round(avg(days_approval_to_investment), 1) AS avg_days_approval_to_investment,
       count(days_approval_to_signing)            AS n_approval_to_signing,
       count(days_signing_to_investment)          AS n_signing_to_investment
FROM gold_portfolio
GROUP BY region
ORDER BY avg_days_approval_to_investment DESC
""", "Each interval averages the projects that have both dates in valid order (A07), so the counts per interval differ.")

answer("Q12", "List Pending projects whose Projected Board Date has passed as of their As of Date but that have not yet been approved.", """
SELECT project_number, project_name, country, industry, projected_board_date, as_of_date,
       datediff(as_of_date, projected_board_date) AS days_overdue,
       round(total_approved_musd, 2) AS proposed_musd
FROM gold_portfolio
WHERE status = 'Pending' AND approval_date IS NULL
  AND projected_board_date < as_of_date
ORDER BY days_overdue DESC
""", "Compared against each record's own As of Date, as the question specifies. Amount is the proposed amount (A04).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## D. Document & project-level queries

# COMMAND ----------

answer("Q13", "[Challenge] Which Active projects have new renewable power generation as their main purpose? Show the count and approved amount by region.", """
SELECT coalesce(region, 'TOTAL') AS region_label, count(*) AS projects,
       round(sum(total_approved_musd), 2) AS approved_musd,
       count_if(text_attributes_need_review) AS awaiting_review
FROM gold_portfolio
WHERE status = 'Active' AND is_new_renewable_generation
GROUP BY ROLLUP(region)
ORDER BY region_label = 'TOTAL', approved_musd DESC
""", "Main purpose classified from the description (A12, A13): excludes transmission/distribution, standalone storage, gas plants, rooftop solar for own use, and lending programmes that merely mention renewables.")

answer("Q13_detail", "[Challenge] Q13 project list", """
SELECT project_number, project_name, region, country, round(total_approved_musd, 2) AS approved_musd,
       new_capacity_mw, description_clean
FROM gold_portfolio WHERE status = 'Active' AND is_new_renewable_generation
ORDER BY region, approved_musd DESC
""", "Evidence for Q13.")

answer("Q14", "How many Summary of Proposed Investment documents were disclosed each year after 2020?", """
SELECT year(date_disclosed) AS year_disclosed, count(*) AS spi_documents
FROM gold_portfolio
WHERE document_type = 'Summary of Proposed Investment' AND year(date_disclosed) > 2020
GROUP BY year(date_disclosed) ORDER BY year_disclosed
""", "After 2020 = 2021 onwards. One document per project row.")

answer("Q15", "Which projects have an Environmental Category = A but are still Pending? Show the count and approved amount by region.", """
SELECT coalesce(region, 'TOTAL') AS region_label, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_or_proposed_musd
FROM gold_portfolio
WHERE environmental_category = 'A' AND status = 'Pending'
GROUP BY ROLLUP(region)
ORDER BY region_label = 'TOTAL', approved_or_proposed_musd DESC
""", "For Pending projects not yet approved the amount is the proposed amount (A04).")

answer("Q16", "Find all projects with Document Type = Environmental & Social Review Summary, broken down by Environmental Category.", """
SELECT environmental_category, count(*) AS projects, round(sum(total_approved_musd), 2) AS total_musd
FROM gold_portfolio
WHERE document_type = 'Environmental & Social Review Summary'
GROUP BY environmental_category ORDER BY environmental_category
""", "Full project list in Q16_detail.")

answer("Q16_detail", "Q16 project list", """
SELECT environmental_category, project_number, project_name, country, status, round(total_approved_musd, 2) AS total_musd
FROM gold_portfolio
WHERE document_type = 'Environmental & Social Review Summary'
ORDER BY environmental_category, total_musd DESC
""", "")

# COMMAND ----------

# MAGIC %md
# MAGIC ## E. Department & product line insights

# COMMAND ----------

answer("Q17", "Show approved investment by Department for projects approved in the last 5 years.", """
SELECT department, count(*) AS projects_approved, round(sum(total_approved_musd), 2) AS approved_musd
FROM gold_portfolio
WHERE approval_date >  add_months((SELECT max(reporting_date) FROM gold_portfolio), -60)
  AND approval_date <= (SELECT max(reporting_date) FROM gold_portfolio)
GROUP BY department ORDER BY approved_musd DESC
""", "Same 5-year window as Q01 (A02). All statuses (A03).")

answer("Q18", "Compare Product Line categories (Loan, Equity, Guarantee, Risk Management) across regions, excluding Dropped projects.", """
SELECT region,
       round(sum(loan_musd), 2)       AS loan_musd,
       round(sum(equity_musd), 2)     AS equity_musd,
       round(sum(guarantee_musd), 2)  AS guarantee_musd,
       round(sum(risk_mgmt_musd), 2)  AS risk_management_musd,
       count_if(product_line = 'Loan') AS n_loan_principal, count_if(product_line = 'Equity') AS n_equity_principal,
       count_if(product_line = 'Guarantee') AS n_guarantee_principal, count_if(product_line = 'Risk Management') AS n_rm_principal
FROM gold_portfolio
WHERE status <> 'Dropped'
GROUP BY region ORDER BY region
""", "Amounts from allocation columns; counts by recorded principal Product Line (A08).")

answer("Q19", "Which industries receive the largest risk management investments, and what share of each industry's investment is risk management?", """
SELECT industry,
       round(sum(risk_mgmt_musd), 2) AS risk_management_musd,
       round(sum(product_alloc_sum_musd), 2) AS total_allocated_musd,
       round(sum(risk_mgmt_musd) / sum(product_alloc_sum_musd) * 100, 1) AS risk_management_share_pct
FROM gold_portfolio
GROUP BY industry ORDER BY risk_management_musd DESC
""", "Share = risk management allocation / sum of all four allocations, so the numerator and denominator are on the same basis (A08). All statuses (A03).")

answer("Q20", "Show the number of projects approved by each Department yearly from 2020 to 2025.", """
SELECT * FROM (
  SELECT department, year(approval_date) AS yr FROM gold_portfolio
  WHERE year(approval_date) BETWEEN 2020 AND 2025
) PIVOT (count(1) FOR yr IN (2020, 2021, 2022, 2023, 2024, 2025))
ORDER BY department
""", "Counted by approval year. All statuses (A03).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## F. Status & risk-based queries

# COMMAND ----------

answer("Q21", "Find all Dropped projects with more than $250M originally approved investment.", """
SELECT project_number, project_name, country, industry, approval_date,
       is_board_approved AS was_board_approved, round(total_approved_musd, 2) AS total_musd
FROM gold_portfolio
WHERE status = 'Dropped' AND total_approved_musd > 250
ORDER BY was_board_approved DESC, total_musd DESC
""", "Lists every Dropped project whose Total exceeds $250M and shows whether the Board had approved it. Strictly 'originally approved' = was_board_approved = true; the others were dropped before approval and their amount was only proposed (A04).")

answer("Q22", "List all Active projects whose first investment came more than 2 years after Board approval.", """
SELECT project_number, project_name, country, approval_date, invested_date,
       days_approval_to_investment, round(days_approval_to_investment / 365.25, 2) AS years_to_first_investment
FROM gold_portfolio
WHERE status = 'Active' AND invested_date > add_months(approval_date, 24)
ORDER BY days_approval_to_investment DESC
""", "More than 2 years = invested date later than approval date + 24 months.")

answer("Q23", "What percentage of projects are Active, Closed, Pending, and Dropped in each region?", """
SELECT * FROM (
  SELECT region, status, round(count(*) * 100.0 / sum(count(*)) OVER (PARTITION BY region), 1) AS pct
  FROM gold_portfolio GROUP BY region, status
) PIVOT (first(pct) FOR status IN ('Active', 'Closed', 'Pending', 'Dropped'))
ORDER BY region
""", "Share of project count within each region (rows sum to 100%).")

# COMMAND ----------

# MAGIC %md
# MAGIC ## G. Text & semantic search queries ([Challenge])

# COMMAND ----------

answer("Q24", "[Challenge] What is the total new renewable generation capacity (MW) of Active and Closed projects, by region, and how many of these projects do not state a capacity?", """
SELECT coalesce(region, 'TOTAL') AS region_label,
       count(*) AS renewable_generation_projects,
       round(sum(new_capacity_mw), 1) AS total_new_capacity_mw,
       count_if(new_capacity_mw IS NULL) AS projects_without_stated_capacity,
       count_if(text_attributes_need_review) AS awaiting_review
FROM gold_portfolio
WHERE status IN ('Active', 'Closed') AND is_new_renewable_generation
GROUP BY ROLLUP(region)
ORDER BY region_label = 'TOTAL', total_new_capacity_mw DESC
""", "Capacity = new MW added by the project (GW converted x1000; expansions count only the added MW; MWh of storage ignored). MW of other sponsors' plants connected by a transmission line are not counted (A13).")

answer("Q25a", "[Challenge] MSME financing (excluding Dropped): number of projects and approved amount", """
SELECT count(*) AS msme_projects, round(sum(total_approved_musd), 2) AS approved_musd,
       count(DISTINCT country) AS countries, count(DISTINCT client_id) AS clients,
       count_if(text_attributes_need_review) AS awaiting_review
FROM gold_portfolio
WHERE status <> 'Dropped' AND is_msme_financing
""", "MSME financing = main purpose is financing micro, small or medium enterprises; excludes SMEs as suppliers or incidental beneficiaries, explicit exclusions and household microloans (A14).")

answer("Q25b", "[Challenge] MSME financing: top 5 countries", """
SELECT country, count(*) AS msme_projects, round(sum(total_approved_musd), 2) AS approved_musd
FROM gold_portfolio
WHERE status <> 'Dropped' AND is_msme_financing
GROUP BY country ORDER BY approved_musd DESC LIMIT 5
""", "Ranked by approved amount.")

answer("Q25c", "[Challenge] MSME financing: main groups of businesses targeted", """
SELECT msme_target_group, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd,
       round(count(*) * 100.0 / sum(count(*)) OVER (), 1) AS share_of_projects_pct
FROM gold_portfolio
WHERE status <> 'Dropped' AND is_msme_financing
GROUP BY msme_target_group ORDER BY projects DESC
""", "Target group extracted from the description (A12).")

answer("Q26a", "[Challenge] Which projects' descriptions describe a different financing product than the one recorded in Product Line? Count by recorded Product Line.", """
SELECT product_line AS recorded_product_line, described_product, count(*) AS projects
FROM gold_portfolio
WHERE described_product IS NOT NULL AND described_product <> product_line
GROUP BY ALL ORDER BY recorded_product_line, projects DESC
""", "Described product = principal instrument named in the text (e.g. 'interest rate swap' = Risk Management; 'X alongside a smaller Y' = X). Projects whose description names no instrument are excluded.")

answer("Q26b", "[Challenge] Q26 project list", """
SELECT project_number, project_name, product_line AS recorded_product_line, described_product,
       round(loan_musd, 2) AS loan_musd, round(equity_musd, 2) AS equity_musd,
       round(guarantee_musd, 2) AS guarantee_musd, round(risk_mgmt_musd, 2) AS risk_mgmt_musd,
       description_clean
FROM gold_portfolio
WHERE described_product IS NOT NULL AND described_product <> product_line
ORDER BY recorded_product_line, project_number
""", "Allocation columns are shown so a reviewer can see which record is likely wrong.")

# COMMAND ----------

# MAGIC %md
# MAGIC ## H. Complex multi-metric analysis

# COMMAND ----------

q27 = answer("Q27", "Bubble chart for the 15 countries with the highest approved investment (excluding Dropped): x = Loan, y = Equity, size = Total.", """
SELECT country, round(sum(loan_musd), 2) AS loan_musd, round(sum(equity_musd), 2) AS equity_musd,
       round(sum(total_approved_musd), 2) AS total_approved_musd
FROM gold_portfolio WHERE status <> 'Dropped'
GROUP BY country ORDER BY total_approved_musd DESC LIMIT 15
""", "Approved = Board total; excludes Dropped as stated.")

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

answer("Q28", "Which projects have a Board-approved total that differs from the sum of their product allocations by more than $1M?", """
SELECT project_number, project_name, status, round(total_approved_musd, 2) AS board_total_musd,
       round(product_alloc_sum_musd, 2) AS sum_of_allocations_musd, round(alloc_gap_musd, 2) AS difference_musd
FROM gold_portfolio
WHERE abs(alloc_gap_musd) > 1
ORDER BY abs(alloc_gap_musd) DESC
""", "Absolute difference > 1.0 USD M. Data-quality finding: reported, not corrected (A08).")

answer("Q29", "List multi-product projects (more than one product with a non-zero allocation) and their totals.", """
SELECT project_number, project_name, product_line AS principal_product, product_count,
       round(loan_musd, 2) AS loan_musd, round(equity_musd, 2) AS equity_musd,
       round(guarantee_musd, 2) AS guarantee_musd, round(risk_mgmt_musd, 2) AS risk_mgmt_musd,
       round(total_approved_musd, 2) AS total_musd
FROM gold_portfolio WHERE is_multi_product
ORDER BY total_musd DESC
""", "All statuses (A03).")

q30 = answer("Q30", "Heatmap of region vs industry based on total approved investment, excluding Dropped projects.", """
SELECT * FROM (
  SELECT region, industry, round(total_approved_musd, 2) AS amt FROM gold_portfolio WHERE status <> 'Dropped'
) PIVOT (sum(amt) FOR industry IN ('Agribusiness', 'Energy', 'Finance', 'Manufacturing', 'Telecom'))
ORDER BY region
""", "Approved = Board total.")

try:
    import plotly.express as px
    h = q30.toPandas().set_index("region")
    px.imshow(h, text_auto=True, aspect="auto", color_continuous_scale="Purples",
              title="Approved investment by region and industry (excl. Dropped), USD M").show()
except ImportError:
    print("plotly not available - use the notebook chart editor (Heatmap) on the Q30 table")

# COMMAND ----------

persist_answers("WS1")

# COMMAND ----------

# MAGIC %sql
# MAGIC SELECT question_id, question, row_count, assumptions FROM answers_register WHERE workstream = 'WS1' ORDER BY question_id
