# Databricks notebook source
# MAGIC %md
# MAGIC # 08_trends — what is going well, what is lacking, month by month
# MAGIC
# MAGIC Reads `certified_investment_portfolio_history` (every reporting month) and builds:
# MAGIC
# MAGIC | Output | What it answers |
# MAGIC |---|---|
# MAGIC | `ref_kpi_definitions` | Which KPIs we track, their SQL, and whether higher or lower is better (from the `trends` section of the config) |
# MAGIC | `kpi_monthly` | Value of every KPI per month, for the whole portfolio and by region, industry, product line, department |
# MAGIC | `kpi_month_over_month` | Each month vs the month before: change, % change and an assessment (**Improving / Deteriorating / Stable**, or **Up / Down** for neutral KPIs) |
# MAGIC | `project_month_changes` | Why a KPI moved: one row per project per change (new project, status change, approval, signing, first disbursement, disbursement, risk-rating up/downgrade, performance worsened/improved, review overdue / cleared, data issue new / resolved) |
# MAGIC | `kpi_latest_scorecard` (view) | Latest month vs the previous one, whole portfolio, worst first |
# MAGIC | `compare_months(month_a, month_b, dimension)` (SQL function) | Any two months side by side, e.g. `SELECT * FROM compare_months('2026-07', '2026-10', 'Region')` |
# MAGIC
# MAGIC **Assessment rule (deterministic, not an LLM):** change below `trends.materiality_pct` % of the earlier value =
# MAGIC Stable; otherwise Improving if it moved in the KPI's "better" direction, Deteriorating if not. All tables are rebuilt
# MAGIC from the history on every run, so a re-uploaded month flows through automatically.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

TR = CFG["trends"]
KPIS = TR["kpis"]
DIMS = TR["dimensions"]
MAT = float(TR.get("materiality_pct", 2.0))
HIST = T("certified_investment_portfolio_history")
assert spark.catalog.tableExists(HIST), f"{HIST} not found: run the monthly pipeline (07_snapshot_month) first."

months = [r[0] for r in spark.sql(f"SELECT DISTINCT reporting_month FROM {HIST} ORDER BY 1").collect()]
print(f"{len(months)} months in history: {[m.isoformat()[:7] for m in months]}; {len(KPIS)} KPIs; dimensions {list(DIMS)}")


def q(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def assessment_sql(change: str, base: str, better: str) -> str:
    """SQL CASE: Stable / Improving / Deteriorating (or Up / Down for neutral KPIs)."""
    return f"""CASE
      WHEN {change} IS NULL THEN NULL
      WHEN abs({change}) <= abs(coalesce({base}, 0)) * {MAT} / 100 OR abs({change}) < 1e-9 THEN 'Stable'
      WHEN {better} = 'neutral' THEN CASE WHEN {change} > 0 THEN 'Up' ELSE 'Down' END
      WHEN ({better} = 'higher') = ({change} > 0) THEN 'Improving'
      ELSE 'Deteriorating' END"""

# COMMAND ----------

# MAGIC %md ## KPI definitions → `ref_kpi_definitions`

# COMMAND ----------

defs = spark.createDataFrame(
    [(k["id"], k["category"], k["name"], k["unit"], k["better"], k["sql"]) for k in KPIS],
    "kpi_id STRING, category STRING, kpi_name STRING, unit STRING, better STRING, sql_expression STRING")
defs.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T("ref_kpi_definitions"))
spark.sql(f"COMMENT ON TABLE {T('ref_kpi_definitions')} IS 'KPIs tracked month by month (config: trends.kpis). better = higher, "
          f"lower or neutral. A change within {MAT}% of the earlier value is Stable.'")

# COMMAND ----------

# MAGIC %md ## Monthly values → `kpi_monthly`

# COMMAND ----------

kpi_cols = ", ".join(f"CAST({k['sql']} AS DOUBLE) AS {k['id']}" for k in KPIS)
unpivot = ", ".join(k["id"] for k in KPIS)
groupings = [("Portfolio", "'All'")] + [(label, f"coalesce(CAST({col} AS STRING), '(blank)')") for label, col in DIMS.items()]
parts = [f"""SELECT reporting_month, {q(label)} AS dimension, {expr} AS dimension_value, {kpi_cols}
             FROM {HIST} GROUP BY ALL""" for label, expr in groupings]
spark.sql(f"""
CREATE OR REPLACE TABLE {T('kpi_monthly')}
COMMENT 'Value of every KPI (ref_kpi_definitions) per reporting month, for the whole portfolio (dimension = Portfolio) and by region, industry, product line and department. Built from certified_investment_portfolio_history.'
AS
WITH wide AS ({' UNION ALL '.join(parts)}),
long AS (SELECT * FROM wide UNPIVOT INCLUDE NULLS (value FOR kpi_id IN ({unpivot})))
SELECT l.reporting_month, date_format(l.reporting_month, 'yyyy-MM') AS month_label, l.dimension, l.dimension_value,
       d.kpi_id, d.category, d.kpi_name, d.unit, d.better, round(l.value, 4) AS value
FROM long l JOIN {T('ref_kpi_definitions')} d USING (kpi_id)
""")
print(f"kpi_monthly: {spark.table(T('kpi_monthly')).count()} rows")

# COMMAND ----------

# MAGIC %md ## Month over month → `kpi_month_over_month`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {T('kpi_month_over_month')}
COMMENT 'Each KPI in each month compared with the previous reporting month: change, % change and assessment (Improving / Deteriorating / Stable; Up / Down for neutral KPIs). Materiality {MAT}%.'
AS
WITH x AS (
  SELECT *, lag(reporting_month) OVER w AS previous_month, lag(value) OVER w AS previous_value
  FROM {T('kpi_monthly')}
  WINDOW w AS (PARTITION BY dimension, dimension_value, kpi_id ORDER BY reporting_month)
)
SELECT reporting_month, month_label, previous_month, dimension, dimension_value, kpi_id, category, kpi_name, unit, better,
       previous_value, value, round(value - previous_value, 4) AS change,
       round(100 * (value - previous_value) / nullif(abs(previous_value), 0), 2) AS change_pct,
       {assessment_sql('value - previous_value', 'previous_value', 'better')} AS assessment
FROM x WHERE previous_month IS NOT NULL
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {T('kpi_latest_scorecard')}
COMMENT 'Latest reporting month vs the previous one, whole portfolio: what is going well (Improving) and what is lacking (Deteriorating), worst first.'
AS SELECT month_label, date_format(previous_month, 'yyyy-MM') AS previous_month_label, category, kpi_id, kpi_name, unit,
          previous_value, value, change, change_pct, assessment
FROM {T('kpi_month_over_month')}
WHERE dimension = 'Portfolio' AND reporting_month = (SELECT max(reporting_month) FROM {T('kpi_month_over_month')})
ORDER BY CASE assessment WHEN 'Deteriorating' THEN 1 WHEN 'Improving' THEN 2 WHEN 'Up' THEN 3 WHEN 'Down' THEN 3 ELSE 4 END,
         abs(coalesce(change_pct, 0)) DESC
""")

# COMMAND ----------

# MAGIC %md ## Any two months → `compare_months(month_a, month_b, dimension)`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE FUNCTION {T('compare_months')}(
  month_a STRING COMMENT 'Earlier month, YYYY-MM (e.g. 2026-07)',
  month_b STRING COMMENT 'Later month, YYYY-MM (e.g. 2026-10)',
  dimension_name STRING DEFAULT 'Portfolio' COMMENT 'Portfolio, Region, Industry, Product line or Department')
RETURNS TABLE (dimension STRING, dimension_value STRING, category STRING, kpi_id STRING, kpi_name STRING, unit STRING,
               value_a DOUBLE, value_b DOUBLE, change DOUBLE, change_pct DOUBLE, assessment STRING)
COMMENT 'Compare every KPI between two reporting months, with an Improving / Deteriorating / Stable assessment. Example: SELECT * FROM compare_months(''2026-07'', ''2026-10'', ''Region'')'
RETURN
  WITH a AS (SELECT * FROM {T('kpi_monthly')} WHERE month_label = substr(month_a, 1, 7) AND dimension = dimension_name),
       b AS (SELECT * FROM {T('kpi_monthly')} WHERE month_label = substr(month_b, 1, 7) AND dimension = dimension_name)
  SELECT coalesce(b.dimension, a.dimension), coalesce(b.dimension_value, a.dimension_value), coalesce(b.category, a.category),
         coalesce(b.kpi_id, a.kpi_id), coalesce(b.kpi_name, a.kpi_name), coalesce(b.unit, a.unit),
         a.value, b.value, round(b.value - a.value, 4),
         round(100 * (b.value - a.value) / nullif(abs(a.value), 0), 2),
         {assessment_sql('(b.value - a.value)', 'a.value', 'coalesce(b.better, a.better)')}
  FROM a FULL OUTER JOIN b ON a.dimension_value = b.dimension_value AND a.kpi_id = b.kpi_id
""")

# COMMAND ----------

# MAGIC %md ## Why it moved → `project_month_changes`

# COMMAND ----------

PERF_RANK = "CASE {c} WHEN 'Performing' THEN 1 WHEN 'Watchlist' THEN 2 WHEN 'Past Due' THEN 3 END"


def ev(cond, change_type, impact, from_v, to_v, amount):
    impact_sql = f"'{impact}'" if impact in ("Positive", "Negative", "Neutral") else impact
    return (f"CASE WHEN {cond} THEN named_struct('change_type', '{change_type}', 'impact', {impact_sql}, "
            f"'from_value', CAST({from_v} AS STRING), 'to_value', CAST({to_v} AS STRING), "
            f"'amount_musd', CAST({amount} AS DOUBLE)) END")


events = [
    ev("p.project_url IS NULL", "NEW_PROJECT", "Neutral", "NULL", "c.status", "c.total_approved_musd"),
    ev("c.project_url IS NULL", "PROJECT_REMOVED", "Neutral", "p.status", "NULL", "p.total_approved_musd"),
    ev("c.status <> p.status", "STATUS_CHANGE",
       "CASE WHEN c.status = 'Dropped' THEN 'Negative' WHEN c.status = 'Active' THEN 'Positive' ELSE 'Neutral' END",
       "p.status", "c.status", "c.total_approved_musd"),
    ev("p.approval_date IS NULL AND c.approval_date IS NOT NULL", "BOARD_APPROVED", "Positive", "NULL", "c.approval_date",
       "c.total_approved_musd"),
    ev("p.signed_date IS NULL AND c.signed_date IS NOT NULL", "SIGNED", "Positive", "NULL", "c.signed_date", "c.total_approved_musd"),
    ev("p.invested_date IS NULL AND c.invested_date IS NOT NULL", "FIRST_DISBURSEMENT", "Positive", "NULL", "c.invested_date",
       "c.disbursed_musd"),
    ev("c.disbursed_musd > coalesce(p.disbursed_musd, 0) + 0.005", "DISBURSED", "Positive", "round(p.disbursed_musd, 2)",
       "round(c.disbursed_musd, 2)", "c.disbursed_musd - coalesce(p.disbursed_musd, 0)"),
    ev("c.internal_risk_rating > p.internal_risk_rating", "RISK_DOWNGRADE", "Negative", "p.internal_risk_rating",
       "c.internal_risk_rating", "c.current_disbursed_exposure_musd"),
    ev("c.internal_risk_rating < p.internal_risk_rating", "RISK_UPGRADE", "Positive", "p.internal_risk_rating",
       "c.internal_risk_rating", "c.current_disbursed_exposure_musd"),
    ev(f"{PERF_RANK.format(c='c.performance_status')} > coalesce({PERF_RANK.format(c='p.performance_status')}, 1) "
       "AND p.project_url IS NOT NULL", "PERFORMANCE_WORSENED", "Negative", "p.performance_status", "c.performance_status",
       "c.disbursed_musd"),
    ev(f"{PERF_RANK.format(c='c.performance_status')} < {PERF_RANK.format(c='p.performance_status')}",
       "PERFORMANCE_IMPROVED", "Positive", "p.performance_status", "c.performance_status", "c.disbursed_musd"),
    ev("c.mon_flag_review_overdue AND NOT coalesce(p.mon_flag_review_overdue, false) AND p.project_url IS NOT NULL",
       "REVIEW_OVERDUE", "Negative", "p.days_since_last_review", "c.days_since_last_review", "c.current_disbursed_exposure_musd"),
    ev("p.mon_flag_review_overdue AND NOT coalesce(c.mon_flag_review_overdue, false) AND c.project_url IS NOT NULL",
       "REVIEW_OVERDUE_CLEARED", "Positive", "p.days_since_last_review", "c.days_since_last_review",
       "c.current_disbursed_exposure_musd"),
    ev("c.needs_review AND NOT coalesce(p.needs_review, false) AND p.project_url IS NOT NULL", "DATA_ISSUE_NEW", "Negative",
       "NULL", "c.dq_flag_ids", "NULL"),
    ev("p.needs_review AND NOT coalesce(c.needs_review, false) AND c.project_url IS NOT NULL", "DATA_ISSUE_RESOLVED", "Positive",
       "p.dq_flag_ids", "NULL", "NULL"),
]
pairs = list(zip(months[:-1], months[1:]))
selects = [f"""
  SELECT DATE'{m.isoformat()}' AS reporting_month, DATE'{prev.isoformat()}' AS previous_month,
         coalesce(c.project_url, p.project_url) AS project_url, coalesce(c.project_name, p.project_name) AS project_name,
         coalesce(c.client_name, p.client_name) AS client_name, coalesce(c.region, p.region) AS region,
         coalesce(c.industry, p.industry) AS industry, coalesce(c.product_line, p.product_line) AS product_line,
         coalesce(c.department, p.department) AS department,
         ev.change_type, ev.impact, ev.from_value, ev.to_value, round(ev.amount_musd, 4) AS amount_musd
  FROM (SELECT * FROM {HIST} WHERE reporting_month = DATE'{m.isoformat()}') c
  FULL OUTER JOIN (SELECT * FROM {HIST} WHERE reporting_month = DATE'{prev.isoformat()}') p ON c.project_url = p.project_url
  LATERAL VIEW explode(filter(array({', '.join(events)}), x -> x IS NOT NULL)) t AS ev""" for prev, m in pairs]

if selects:
    spark.sql(f"""
    CREATE OR REPLACE TABLE {T('project_month_changes')}
    COMMENT 'One row per project per change between consecutive reporting months: the evidence behind every KPI movement. impact = Positive / Negative / Neutral; amount_musd = the money concerned.'
    AS {' UNION ALL '.join(selects)}""")
    display(spark.sql(f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, change_type, impact, count(*) AS projects,
                                 round(sum(amount_musd), 1) AS amount_musd
                          FROM {T('project_month_changes')} GROUP BY ALL ORDER BY month, projects DESC"""))  # noqa: F821
else:
    print("Only one month in history: month-to-month changes appear once a second month is loaded.")

# COMMAND ----------

# MAGIC %md ## Latest month: going well vs lacking

# COMMAND ----------

if len(months) > 1:
    display(spark.table(T("kpi_latest_scorecard")))  # noqa: F821
    print("Where it got worse most (latest month, by breakdown):")
    display(spark.sql(f"""
      SELECT dimension, dimension_value, kpi_name, previous_value, value, change, change_pct
      FROM {T('kpi_month_over_month')}
      WHERE reporting_month = (SELECT max(reporting_month) FROM {T('kpi_month_over_month')})
        AND dimension <> 'Portfolio' AND assessment = 'Deteriorating'
      ORDER BY abs(coalesce(change_pct, 0)) DESC LIMIT 15"""))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Trend charts (whole portfolio)

# COMMAND ----------

import matplotlib.pyplot as plt  # noqa: E402

CHART_KPIS = ["R01", "R02", "R04", "M01", "D01", "G05"]
pdf = spark.sql(f"""SELECT month_label, kpi_id, kpi_name, value FROM {T('kpi_monthly')}
                    WHERE dimension = 'Portfolio' AND kpi_id IN ({', '.join(q(k) for k in CHART_KPIS)})
                    ORDER BY month_label""").toPandas()
if len(months) > 1 and not pdf.empty:
    fig, axes = plt.subplots(2, 3, figsize=(15, 7))
    for ax, kpi in zip(axes.flat, CHART_KPIS):
        d = pdf[pdf.kpi_id == kpi]
        ax.plot(d.month_label, d.value, marker="o")
        ax.set_title(d.kpi_name.iloc[0] if len(d) else kpi, fontsize=10)
        ax.tick_params(axis="x", rotation=45)
        ax.grid(alpha=0.3)
    fig.tight_layout()
    plt.show()
