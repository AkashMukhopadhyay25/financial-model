# Databricks notebook source
# MAGIC %md
# MAGIC # 06_dq_checks — portfolio-level checks: the numbers hold together end to end
# MAGIC
# MAGIC Stage 3 checks every **row** against its contract. This notebook checks the **portfolio as a whole**, as an independent
# MAGIC second line of defence before any answer is produced. Every check, every run, is stored in **`ops_dq_checks`** with its
# MAGIC SQL, the expected and actual value, and pass/fail.
# MAGIC
# MAGIC | Severity | Meaning |
# MAGIC |---|---|
# MAGIC | `blocking` | The job **fails** if it does not pass, so WS1 answers are never produced from inconsistent data. |
# MAGIC | `warning` | Recorded and shown; needs a human look but does not stop the job. |
# MAGIC | `info` | Context, e.g. comparison with the first delivery. Never stops the job. |
# MAGIC
# MAGIC | Group | What it proves |
# MAGIC |---|---|
# MAGIC | **R** reconciliation | Nothing was lost or invented: raw rows = validated + quarantined; raw dollar totals = validated + quarantined; certified = validated. Expected values are **computed from the data**, never typed in. |
# MAGIC | **K** keys | `project_url` is unique; every monitoring row has a project; project numbers agree; one name per client. |
# MAGIC | **S** structure | Dropped ↔ no monitoring, Pending ↔ no disbursement, disbursed never above approved. |
# MAGIC | **V** values | Every category value is one the contract allows (lists read from the contracts); no unparseable dates or amounts. |
# MAGIC | **F** first delivery | Totals and counts compared with the first delivery (`reference_figures` in config). Info only. |
# MAGIC | **D**, **T** findings | Flag counts and text-review counts, for the record. Info only. |
# MAGIC
# MAGIC Also builds the view **`ops_dq_issues`**: every open issue in one list (project flags, monitoring flags, text attributes
# MAGIC awaiting review), with the project name, owner and message. This is the reviewers' work list.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

import uuid
from datetime import datetime, timezone

from ifc_common import load_contracts  # noqa: E402

CONTRACTS = load_contracts(CFG["_contracts_dir"])
TOL = float(CFG.get("dq_checks", {}).get("control_total_tolerance_musd", 0.05))
REF = CFG.get("reference_figures", {})
RUN_ID = str(uuid.uuid4())

P, M = CONTRACTS["projects"], CONTRACTS["monitoring"]
RAW_P, RAW_M = T(P["targets"]["raw"]) + "_current", T(M["targets"]["raw"]) + "_current"
VAL_P, VAL_M = T(P["targets"]["validated"]), T(M["targets"]["validated"])
QUA_P, QUA_M = T(P["targets"]["quarantine"]), T(M["targets"]["quarantine"])
CERT = T("certified_investment_portfolio")
TEXT = T("enriched_project_text_features")
RULES = T("enriched_rule_features")


def sql_list(values) -> str:
    return ", ".join(str(v) if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'" for v in values)


def schema_col(contract, target):
    return next(c for c in contract["schema"] if c["target"] == target)


# COMMAND ----------

# MAGIC %md ## Check definitions
# MAGIC Each check: id, severity, description, `actual` SQL returning one number, and either a fixed `expected` number or an
# MAGIC `expected_sql` computed from the data. `tol` is the allowed absolute difference.

# COMMAND ----------

CHECKS = []


def check(cid, severity, description, actual, expected=None, expected_sql=None, tol=0):
    CHECKS.append(dict(check_id=cid, severity=severity, description=description, actual_sql=actual.strip(),
                       expected=expected, expected_sql=expected_sql.strip() if expected_sql else None, tol=tol))


# ---- R: reconciliation (expected values computed from the data) -------------------------------------------------
check("R01", "blocking", "Projects: raw rows = validated + quarantined",
      f"SELECT (SELECT count(*) FROM {VAL_P}) + (SELECT count(*) FROM {QUA_P})",
      expected_sql=f"SELECT count(*) FROM {RAW_P}")
check("R02", "blocking", "Monitoring: raw rows = validated + quarantined",
      f"SELECT (SELECT count(*) FROM {VAL_M}) + (SELECT count(*) FROM {QUA_M})",
      expected_sql=f"SELECT count(*) FROM {RAW_M}")
AMOUNTS = [(P, RAW_P, VAL_P, QUA_P, c["target"]) for c in P["schema"] if c["type"] == "double"] + \
          [(M, RAW_M, VAL_M, QUA_M, c["target"]) for c in M["schema"] if c["type"] == "double"]
for i, (_, raw, val, qua, col) in enumerate(AMOUNTS, start=3):
    check(f"R{i:02d}", "blocking", f"Control total {col}: raw = validated + quarantined (USD M)",
          f"SELECT round(coalesce((SELECT sum({col}) FROM {val}), 0) "
          f"+ coalesce((SELECT sum(try_cast({col} AS DOUBLE)) FROM {qua}), 0), 2)",
          expected_sql=f"SELECT round(sum(try_cast({col} AS DOUBLE)), 2) FROM {raw}", tol=TOL)
n = 3 + len(AMOUNTS)
check(f"R{n:02d}", "blocking", "Certified portfolio has exactly one row per validated project",
      f"SELECT count(*) FROM {CERT}", expected_sql=f"SELECT count(*) FROM {VAL_P}")
check(f"R{n + 1:02d}", "blocking", "Control total total_approved_musd: certified = validated (USD M)",
      f"SELECT round(sum(total_approved_musd), 2) FROM {CERT}",
      expected_sql=f"SELECT round(sum(total_approved_musd), 2) FROM {VAL_P}", tol=TOL)
check(f"R{n + 2:02d}", "blocking", "Control total disbursed_musd: certified = validated monitoring (USD M)",
      f"SELECT round(sum(disbursed_musd), 2) FROM {CERT}",
      expected_sql=f"SELECT round(sum(disbursed_musd), 2) FROM {VAL_M}", tol=TOL)
check(f"R{n + 3:02d}", "blocking", "Every certified project has text attributes (enrichment ran on the current data)",
      f"SELECT count(*) FROM {CERT} c LEFT ANTI JOIN {TEXT} t USING (project_url)", expected=0)

# ---- K: keys ---------------------------------------------------------------------------------------------------
check("K01", "blocking", "project_url unique in validated projects",
      f"SELECT count(*) - count(DISTINCT project_url) FROM {VAL_P}", expected=0)
check("K02", "blocking", "project_url unique in validated monitoring",
      f"SELECT count(*) - count(DISTINCT project_url) FROM {VAL_M}", expected=0)
check("K03", "blocking", "project_url unique in the certified portfolio (the join did not duplicate rows)",
      f"SELECT count(*) - count(DISTINCT project_url) FROM {CERT}", expected=0)
check("K04", "blocking", "Monitoring rows without a portfolio project",
      f"SELECT count(*) FROM {VAL_M} m LEFT ANTI JOIN {VAL_P} p USING (project_url)", expected=0)
check("K05", "blocking", "Project number disagrees across tables for the same project_url",
      f"SELECT count(*) FROM {VAL_M} m JOIN {VAL_P} p USING (project_url) WHERE m.project_number <> p.project_number",
      expected=0)
check("K06", "blocking", "Client ID maps to exactly one client name",
      f"SELECT count(*) FROM (SELECT client_id FROM {VAL_M} GROUP BY client_id HAVING count(DISTINCT client_name) > 1)",
      expected=0)
check("K07", "info", "Distinct project numbers (fewer than projects: project_number is not a key, A01)",
      f"SELECT count(DISTINCT project_number) FROM {VAL_P}", expected=REF.get("distinct_project_numbers"))

# ---- S: structure ----------------------------------------------------------------------------------------------
check("S01", "blocking", "Dropped projects with a monitoring record",
      f"SELECT count(*) FROM {CERT} WHERE status = 'Dropped' AND is_monitored", expected=0)
check("S02", "blocking", "Non-Dropped projects without a monitoring record",
      f"SELECT count(*) FROM {CERT} WHERE status <> 'Dropped' AND NOT is_monitored", expected=0)
check("S03", "blocking", "Pending projects with a performance status or disbursement",
      f"SELECT count(*) FROM {CERT} WHERE status = 'Pending' AND (performance_status IS NOT NULL OR disbursed_musd IS NOT NULL)",
      expected=0)
check("S04", "warning", "Closed projects with days since last review (the dictionary says blank)",
      f"SELECT count(*) FROM {CERT} WHERE status = 'Closed' AND days_since_last_review IS NOT NULL", expected=0)
check("S05", "blocking", "Disbursed exceeds approved",
      f"SELECT count(*) FROM {CERT} WHERE disbursed_musd > total_approved_musd + {CFG['thresholds']['amount_reconciliation_tolerance_musd']}",
      expected=0)

# ---- V: values (allowed lists read from the contracts) -----------------------------------------------------------
v = 1
for contract, table in [(P, VAL_P), (M, VAL_M)]:
    for col in contract["schema"]:
        if col.get("allowed"):
            check(f"V{v:02d}", "blocking", f"{contract['contract']['name']}.{col['target']} outside the contract's allowed values",
                  f"SELECT count(*) FROM {table} WHERE {col['target']} IS NOT NULL AND {col['target']} NOT IN ({sql_list(col['allowed'])})",
                  expected=0)
            v += 1
for contract, raw, table in [(P, RAW_P, VAL_P), (M, RAW_M, VAL_M)]:
    typed = [c["target"] for c in contract["schema"] if c["type"] != "string"]
    cond = " OR ".join(f"(nullif(trim(r.{c}), '') IS NOT NULL AND t.{c} IS NULL)" for c in typed)
    check(f"V{v:02d}", "blocking", f"{contract['contract']['name']}: values present in the file but lost when typed (dates, numbers)",
          f"SELECT count(*) FROM {raw} r JOIN {table} t ON trim(r.project_url) = t.project_url WHERE {cond}", expected=0)
    v += 1

# ---- F: first delivery (info only; nothing blocks on a hard-coded figure) ----------------------------------------
FIRST = [("F01", "projects_rows", f"SELECT count(*) FROM {VAL_P}", "Validated projects vs first delivery"),
         ("F02", "monitoring_rows", f"SELECT count(*) FROM {VAL_M}", "Validated monitoring rows vs first delivery")]
FIRST += [(f"F{i:02d}", col, f"SELECT round(sum({col}), 2) FROM {VAL_M if col == 'disbursed_musd' else VAL_P}",
           f"Total {col} vs first delivery (USD M)")
          for i, col in enumerate(["total_approved_musd", "amt_loan_musd", "amt_equity_musd", "amt_guarantee_musd",
                                   "amt_risk_mgmt_musd", "disbursed_musd"], start=3)]
for cid, key, sql, desc in FIRST:
    if REF.get(key) is not None:
        check(cid, "info", desc, sql, expected=REF[key], tol=TOL if "musd" in key else 0)

# ---- D, T: findings for the record (info) ------------------------------------------------------------------------
for i, r in enumerate(P.get("flag_rules", []), start=1):
    check(f"D{i:02d}", "info", f"Projects flagged {r['id']} {r['name']} ({r['severity']})",
          f"SELECT count_if(flag_{r['name']}) FROM {CERT}", expected=r.get("expected_initial"))
k = len(P.get("flag_rules", [])) + 1
for j, r in enumerate(M.get("flag_rules", []), start=k):
    check(f"D{j:02d}", "info", f"Projects flagged {r['id']} {r['name']} ({r['severity']})",
          f"SELECT count_if(mon_flag_{r['name']}) FROM {CERT}", expected=r.get("expected_initial"))
check("D90", "info", "Board total differs from product allocations by more than the Q28 threshold (A08)",
      f"SELECT count_if(abs(alloc_gap_musd) > {Q28_ALLOCATION_THRESHOLD_MUSD}) FROM {CERT}", expected=REF.get("q28_gap_projects"))
check("D91", "info", "Projects needing review (warning or high flag on project or monitoring record)",
      f"SELECT count_if(needs_review) FROM {CERT}")
check("T01", "warning", "Text attributes awaiting human review (A12)", f"SELECT count_if(needs_review) FROM {TEXT}")
check("T02", "info", "Rule-based: new renewable generation projects", f"SELECT count_if(rb_is_new_renewable_generation) FROM {RULES}",
      expected=REF.get("rule_new_renewable_projects"))
check("T03", "info", "Rule-based: MSME financing projects", f"SELECT count_if(rb_is_msme_financing) FROM {RULES}")
check("T04", "warning", "Descriptions with no usable LLM result (sent to rules only and flagged)",
      f"SELECT count_if(review_reason = 'llm_missing') FROM {TEXT}", expected=0)

print(f"{len(CHECKS)} checks defined")

# COMMAND ----------

# MAGIC %md ## Run and store

# COMMAND ----------


def scalar(sql):
    v = spark.sql(sql).collect()[0][0]
    return float(v) if v is not None else None


rows = []
for c in CHECKS:
    actual = scalar(c["actual_sql"])
    expected = scalar(c["expected_sql"]) if c["expected_sql"] else (None if c["expected"] is None else float(c["expected"]))
    passed = True if expected is None else (actual is not None and abs(actual - expected) <= c["tol"])
    rows.append((RUN_ID, c["check_id"], c["severity"], c["description"], c["actual_sql"], c["expected_sql"],
                 expected, actual, float(c["tol"]), passed))

schema = ("run_id STRING, check_id STRING, severity STRING, description STRING, check_sql STRING, expected_sql STRING, "
          "expected DOUBLE, actual DOUBLE, tolerance DOUBLE, passed BOOLEAN")
spark.sql(f"""CREATE TABLE IF NOT EXISTS {T('ops_dq_checks')} ({schema}, checked_at TIMESTAMP)
              COMMENT 'Portfolio-level data-quality checks, every run: expected vs actual, with the SQL used. Blocking failures stop the pipeline.'""")
from pyspark.sql import functions as F  # noqa: E402

result = spark.createDataFrame(rows, schema).withColumn("checked_at", F.lit(datetime.now(timezone.utc)).cast("timestamp"))
result.write.mode("append").saveAsTable(T("ops_dq_checks"))
display(result.select("check_id", "severity", "description", "expected", "actual", "passed").orderBy("check_id"))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Work list for reviewers: `ops_dq_issues`

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE VIEW {T('ops_dq_issues')}
COMMENT 'Every open data-quality issue in one list: project flags, monitoring flags and text attributes awaiting review. One row per project per issue, with owner and message.'
AS
SELECT i.record_key AS project_url, p.project_name, i.source, i.rule_id, i.rule_name, i.severity, i.owner,
       i.description, i.message, i._source_file, i._source_row_number
FROM {T(P['targets']['issues'])} i LEFT JOIN {VAL_P} p ON p.project_url = i.record_key
UNION ALL
SELECT i.record_key, p.project_name, i.source, i.rule_id, i.rule_name, i.severity, i.owner,
       i.description, i.message, i._source_file, i._source_row_number
FROM {T(M['targets']['issues'])} i LEFT JOIN {VAL_P} p ON p.project_url = i.record_key
UNION ALL
SELECT t.project_url, p.project_name, 'text_features', 'T-REVIEW', 'text_attributes_need_review', 'warning', 'Data team',
       'LLM and rule extraction disagree on a text attribute; a reviewer decides in ref_text_feature_overrides (A12)',
       concat('Text attributes need review: ', t.review_reason, '.'), p._source_file, p._source_row_number
FROM {TEXT} t JOIN {VAL_P} p USING (project_url)
WHERE t.needs_review
""")
display(spark.sql(f"SELECT source, severity, owner, count(*) AS issues FROM {T('ops_dq_issues')} GROUP BY ALL ORDER BY issues DESC"))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Sanity view
# MAGIC Dropped → no monitoring; Pending → monitored but no performance or disbursement; Active and Closed → complete.

# COMMAND ----------

display(spark.sql(f"""
  SELECT status, count(*) AS projects, count_if(is_monitored) AS monitored,
         count(performance_status) AS with_performance, count(disbursed_musd) AS with_disbursement,
         round(sum(current_disbursed_exposure_musd), 1) AS current_exposure_musd,
         round(sum(undisbursed_commitment_musd), 1) AS undisbursed_commitment_musd
  FROM {CERT} GROUP BY status ORDER BY projects DESC"""))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Verdict

# COMMAND ----------

failed = [r for r in rows if not r[9]]
for r in failed:
    print(f"[{'FAIL' if r[2] == 'blocking' else r[2].upper()}] {r[1]} {r[3]}: expected {r[6]}, actual {r[7]}")
blocking = [r for r in failed if r[2] == "blocking"]
if blocking:
    raise RuntimeError(f"{len(blocking)} blocking data-quality check(s) failed: {[r[1] for r in blocking]}. "
                       f"See {T('ops_dq_checks')} (run_id {RUN_ID}). WS1 answers must not be produced from this data.")
print(f"All {sum(1 for r in rows if r[2] == 'blocking')} blocking checks passed "
      f"({len(failed)} non-blocking differences listed above). Run {RUN_ID}.")
