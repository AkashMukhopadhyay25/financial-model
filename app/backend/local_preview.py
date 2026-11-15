"""
Local preview database for developing the app without Databricks.

Builds `app/.preview/preview.duckdb` from the source CSVs in `data/`:
  1. runs the real pipeline stages 1-3 (schema gate -> raw -> validate) locally, with the SQLite adapter in tests/;
  2. builds a simplified `certified_investment_portfolio` (the columns the app reads; no text attributes) in DuckDB;
  3. builds `certified_client_scorecard` and `certified_early_warning` with the SAME SQL as 01_data/07_client_views
     (00_setup/portfolio_sql.py);
  4. builds `ws3_recommendations` with the WS3 primary rule, plus minimal `answers_register`, `ref_assumptions`
     and `ops_*` tables.

Preview figures are for UI work only. The certified figures are the ones on Databricks.

    python -m app.backend.local_preview          # from the repo root
"""
import json
import os
import runpy
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[2]
PREVIEW_DIR = REPO / "app" / ".preview"
DB_PATH = PREVIEW_DIR / "preview.duckdb"
SOURCE_FILES = ["synthetic_ifc_projects_5000.csv", "synthetic_project_monitoring.csv"]
PREVIEW_MONTH = "2026-06"  # reporting month of the first delivery (latest As of Date 2026-06-30)


def _run_stages_1_to_3(work: Path, cfg: dict) -> Path:
    """Schema gate, raw load and validation on the source files; returns the SQLite database path."""
    landing = work / "landing"
    month_dir = landing / "incoming" / PREVIEW_MONTH  # the schema gate requires a month folder (incoming/YYYY-MM/)
    month_dir.mkdir(parents=True)
    for f in SOURCE_FILES:
        shutil.copy(REPO / "data" / f, month_dir / f)
    cfg = json.loads(json.dumps(cfg))
    cfg["environment"]["landing_root"] = str(landing)
    cfg["environment"]["contracts_dir"] = str(REPO / "contracts")
    cfg_path = work / "config.yml"
    cfg_path.write_text(yaml.safe_dump(cfg))
    os.environ["IFC_PIPELINE_CONFIG"] = str(cfg_path)
    for p in [REPO / "tests", REPO / "00_setup"]:
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    runpy.run_path(str(REPO / "01_data" / "01_schema_gate.py"), run_name="__main__")
    runpy.run_path(str(REPO / "01_data" / "02_load_raw.py"), run_name="__main__")
    from sqlite_dialect import SqliteDialect

    stage3 = runpy.run_path(str(REPO / "01_data" / "03_validate.py"), run_name="preview")
    d = SqliteDialect(work / "db")
    tables = landing / "_local_tables"
    prefix = f"{cfg['environment']['catalog']}.{cfg['environment']['schema']}."
    d.load_raw_csv(tables / f"{prefix}raw_projects.csv", "raw_projects")
    d.load_raw_csv(tables / f"{prefix}raw_monitoring.csv", "raw_monitoring")
    stage3["run_validate"](str(cfg_path), dialect=d)
    return work / "db" / "main.db"


CERTIFIED_SQL = """
CREATE OR REPLACE TABLE certified_investment_portfolio AS
SELECT
  p.project_url, p.project_number, p.project_name, p.document_type, CAST(p.date_disclosed AS DATE) AS date_disclosed,
  p.product_line, p.region, p.region_as_reported, p.country, p.wb_country_code, p.industry,
  p.environmental_category, p.department, p.status,
  CAST(p.projected_board_date AS DATE) AS projected_board_date, CAST(p.approval_date AS DATE) AS approval_date,
  CAST(p.signed_date AS DATE) AS signed_date, CAST(p.invested_date AS DATE) AS invested_date,
  CAST(p.as_of_date AS DATE) AS as_of_date, max(CAST(p.as_of_date AS DATE)) OVER () AS reporting_date,
  p.amt_loan_musd, p.amt_equity_musd, p.amt_guarantee_musd, p.amt_risk_mgmt_musd, p.total_approved_musd,
  p.amt_loan_musd + p.amt_equity_musd + p.amt_guarantee_musd + p.amt_risk_mgmt_musd AS product_alloc_sum_musd,
  p.total_approved_musd - (p.amt_loan_musd + p.amt_equity_musd + p.amt_guarantee_musd + p.amt_risk_mgmt_musd) AS alloc_gap_musd,
  p.approval_date IS NOT NULL AS is_board_approved, p.signed_date IS NOT NULL AS is_signed,
  p.invested_date IS NOT NULL AS is_invested, p.signed_date IS NOT NULL AND p.status <> 'Dropped' AS is_committed,
  year(CAST(p.approval_date AS DATE)) AS approval_year,
  m.project_url IS NOT NULL AS is_monitored, m.client_id, m.client_name, m.internal_risk_rating, m.currency,
  m.climate_flag, CAST(m.is_climate_related AS BOOLEAN) AS is_climate_related, m.disbursed_musd, m.performance_status,
  m.days_since_last_review,
  CASE WHEN p.status = 'Active' THEN coalesce(m.disbursed_musd, 0) ELSE 0 END AS current_disbursed_exposure_musd,
  CASE WHEN p.status = 'Active' THEN greatest(p.total_approved_musd - coalesce(m.disbursed_musd, 0), 0)
       WHEN p.status = 'Pending' AND p.signed_date IS NOT NULL THEN p.total_approved_musd ELSE 0 END AS undisbursed_commitment_musd,
  CASE WHEN p.status = 'Pending' AND p.signed_date IS NULL THEN p.total_approved_musd ELSE 0 END AS pipeline_unsigned_musd,
  CASE WHEN m.performance_status = 'Past Due' THEN {ecl} * coalesce(m.disbursed_musd, 0) ELSE 0 END AS expected_credit_loss_musd,
  CASE m.performance_status WHEN 'Past Due' THEN 'RED' WHEN 'Watchlist' THEN 'AMBER' WHEN 'Performing' THEN 'GREEN'
       WHEN 'Completed' THEN 'CLOSED_OK' WHEN 'Exited at a loss' THEN 'CLOSED_LOSS' ELSE 'NOT_APPLICABLE' END AS risk_flag,
  CAST(NULL AS BOOLEAN) AS is_new_renewable_generation, CAST(NULL AS DOUBLE) AS new_capacity_mw,
  false AS text_attributes_need_review,
  CAST(p.flag_board_date_passed AS BOOLEAN) AS flag_board_date_passed,
  CAST(p.flag_outdated_record AS BOOLEAN) AS flag_outdated_record,
  CAST(p.flag_over_allocated AS BOOLEAN) AS flag_over_allocated,
  CAST(p.flag_under_allocated AS BOOLEAN) AS flag_under_allocated,
  coalesce(CAST(m.flag_review_overdue AS BOOLEAN), false) AS mon_flag_review_overdue,
  coalesce(CAST(p.needs_review AS BOOLEAN), false) OR coalesce(CAST(m.needs_review AS BOOLEAN), false) AS needs_review,
  CASE greatest(CASE p.dq_max_severity WHEN 'high' THEN 3 WHEN 'warning' THEN 2 WHEN 'info' THEN 1 ELSE 0 END,
                CASE m.dq_max_severity WHEN 'high' THEN 3 WHEN 'warning' THEN 2 WHEN 'info' THEN 1 ELSE 0 END)
       WHEN 3 THEN 'high' WHEN 2 THEN 'warning' WHEN 1 THEN 'info' ELSE 'none' END AS dq_max_severity,
  concat_ws(', ', nullif(p.review_owners, ''), nullif(m.review_owners, '')) AS review_owners,
  concat_ws(' | ', nullif(p.dq_messages, ''), nullif(m.dq_messages, '')) AS dq_messages,
  concat_ws(',', nullif(p.dq_flag_ids, ''), nullif(m.dq_flag_ids, '')) AS dq_flag_ids,
  coalesce(p.dq_flag_count, 0) + coalesce(m.dq_flag_count, 0) AS dq_flag_count
FROM vp p LEFT JOIN vm m ON p.project_url = m.project_url
"""

WS2_Q2_SQL = """SELECT coalesce(performance_status, 'TOTAL') AS status_label,
       count(*) AS projects,
       round(sum(total_approved_musd), 2) AS approved_musd,
       round(sum(disbursed_musd), 2) AS disbursed_capital_tied_up_musd,
       round(sum(undisbursed_commitment_musd), 2) AS undisbursed_commitment_musd,
       round(sum(expected_credit_loss_musd), 2) AS expected_credit_loss_musd
FROM certified_investment_portfolio
WHERE environmental_category = 'A' AND performance_status IN ('Past Due', 'Watchlist')
GROUP BY ROLLUP(performance_status)
ORDER BY status_label = 'TOTAL', status_label"""


def build(force: bool = False) -> Path:
    if DB_PATH.exists() and not force:
        return DB_PATH
    missing = [f for f in SOURCE_FILES if not (REPO / "data" / f).is_file()]
    if missing:
        raise FileNotFoundError(f"Local preview needs the source files in data/: {missing}")
    sys.path.insert(0, str(REPO / "00_setup"))
    from portfolio_sql import client_scorecard_sql, early_warning_sql

    cfg = yaml.safe_load((REPO / "config" / "pipeline_config.yml").read_text())
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    work = PREVIEW_DIR / "work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    sqlite_db = _run_stages_1_to_3(work, cfg)

    sq = sqlite3.connect(sqlite_db)
    vp = pd.read_sql("SELECT * FROM validated_projects", sq)
    vm = pd.read_sql("SELECT * FROM validated_monitoring", sq)
    dq_summary = pd.read_sql("SELECT * FROM ops_dq_run_summary", sq)
    issues = pd.concat([pd.read_sql(f"SELECT * FROM {t}", sq) for t in
                        ["validated_projects_dq_issues", "validated_monitoring_dq_issues"]], ignore_index=True)
    sq.close()

    tmp = DB_PATH.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.register("vp_df", vp)
    con.register("vm_df", vm)
    con.execute("CREATE TABLE vp AS SELECT * FROM vp_df")
    con.execute("CREATE TABLE vm AS SELECT * FROM vm_df")
    con.execute(CERTIFIED_SQL.format(ecl=cfg["business"]["ecl_loss_rate"]))
    con.execute(f"CREATE OR REPLACE TABLE certified_client_scorecard AS {client_scorecard_sql('certified_investment_portfolio', cfg)}")
    con.execute(f"CREATE OR REPLACE TABLE certified_early_warning AS {early_warning_sql('certified_client_scorecard', cfg)}")

    # WS3: primary rule from the WS3 notebook (two largest CONTINUE exposures, two largest distressed exposures)
    sc = con.execute("SELECT * FROM certified_client_scorecard").df()
    sc["distressed_musd"] = sc["past_due_disbursed_musd"].fillna(0) + sc["watchlist_disbursed_musd"].fillna(0)
    picks = [("CONTINUE", sc[sc.band == "CONTINUE"].nlargest(2, "exposure_affected_musd")),
             ("REDUCE_OR_REVIEW", sc[sc.band == "REDUCE_OR_REVIEW"].nlargest(2, "distressed_musd"))]
    recs = []
    for rec, df in picks:
        for _, s in df.iterrows():
            action = (f"Continue to invest: keep the ${s.undisbursed_commitment_musd:,.0f}M undisbursed commitments on schedule."
                      if rec == "CONTINUE" else
                      f"Reduce exposure / place under review: freeze further drawdowns on the ${s.undisbursed_commitment_musd:,.0f}M "
                      f"undisbursed commitments pending credit review; provision ${s.expected_credit_loss_musd:,.0f}M ECL.")
            recs.append(dict(recommendation=rec, client_id=s.client_id, client_name=s.client_name,
                             primary_industry=s.primary_industry, primary_region=s.primary_region,
                             current_disbursed_exposure_musd=s.current_disbursed_exposure_musd,
                             undisbursed_commitment_musd=s.undisbursed_commitment_musd,
                             exposure_affected_musd=s.exposure_affected_musd,
                             expected_credit_loss_musd=s.expected_credit_loss_musd, health_score=s.health_score,
                             evidence_summary=s.band_evidence, suggested_action=action,
                             team_rationale="Selected by the documented ranking rule (preview)",
                             requires_human_review=True, review_owner="Credit Risk Committee"))
    con.register("recs_df", pd.DataFrame(recs))
    con.execute("CREATE TABLE ws3_recommendations AS SELECT *, now() AS generated_at FROM recs_df")

    # answers_register: WS1 questions (no SQL in preview), WS2 Q2 computed with its certified SQL
    now = datetime.now(timezone.utc).isoformat()
    lib = json.loads((REPO / "app" / "backend" / "question_library.json").read_text())
    ws2 = con.execute(WS2_Q2_SQL).df()
    rows = [dict(workstream="WS1", question_id=q["question_id"], question=q["question"], sql_text=None,
                 assumptions="Certified SQL is available on Databricks (local preview).", assumption_ids=None,
                 row_count=None, result_preview_json=None, computed_at=now) for q in lib]
    rows.append(dict(workstream="WS2", question_id="WS2_Q2_exposure_and_ecl",
                     question="How much of IFC's disbursed capital is tied up in these projects, and how much should IFC "
                              "set aside to cover potential losses on those that are Past Due?",
                     sql_text=WS2_Q2_SQL, assumptions="ECL = 60% x disbursed on Past Due projects only (A11).",
                     assumption_ids="A01,A09,A10,A11,A17", row_count=len(ws2),
                     result_preview_json=ws2.to_json(orient="records"), computed_at=now))
    con.register("ans_df", pd.DataFrame(rows))
    con.execute("CREATE TABLE answers_register AS SELECT * FROM ans_df")

    # ref_assumptions: the real notebook needs Spark; the preview lists IDs and topics only
    topics = ["Join key", "Reporting date", "Status default", "Board approval", "Committed", "Regions", "Lifecycle intervals",
              "Amount measures", "Current exposure", "Undisbursed commitment", "Expected credit loss", "New renewable generation",
              "MSME financing", "Described product", "Client bands", "Currency", "Snapshot dates", "Review overdue",
              "Board date passed", "Quarantine versus flag", "Data contracts and the schema gate", "Early-warning signals"]
    con.register("asm_df", pd.DataFrame({"assumption_id": [f"A{i:02d}" for i in range(1, 23)], "topic": topics,
                                         "statement": ["Full wording in ref_assumptions on Databricks (preview)."] * 22}))
    con.execute("CREATE TABLE ref_assumptions AS SELECT * FROM asm_df")

    con.register("dq_df", dq_summary)
    con.execute("CREATE TABLE ops_dq_run_summary AS SELECT * FROM dq_df")
    con.register("iss_df", issues)
    con.execute("CREATE TABLE ops_dq_issues AS SELECT * FROM iss_df")
    con.execute("CREATE TABLE ops_review_requests (requested_at TIMESTAMP, requested_by VARCHAR, entity_type VARCHAR, "
                "entity_id VARCHAR, entity_name VARCHAR, action VARCHAR, note VARCHAR, source_page VARCHAR)")
    con.execute(f"CREATE TABLE ops_preview_info AS SELECT TIMESTAMP '{now[:19].replace('T', ' ')}' AS built_at")
    con.execute("DROP TABLE vp")
    con.execute("DROP TABLE vm")
    con.close()
    tmp.replace(DB_PATH)
    shutil.rmtree(work, ignore_errors=True)
    return DB_PATH


if __name__ == "__main__":
    path = build(force=True)
    con = duckdb.connect(str(path), read_only=True)
    print(con.execute("SELECT count(*), round(sum(total_approved_musd), 2) FROM certified_investment_portfolio").fetchall())
    print(con.execute(WS2_Q2_SQL).df().to_string())
    print(con.execute("SELECT band, count(*) FROM certified_client_scorecard GROUP BY band ORDER BY band").fetchall())
    print(con.execute("SELECT priority, count(*) FROM certified_early_warning GROUP BY priority").fetchall())
    print(con.execute("SELECT recommendation, client_name FROM ws3_recommendations").fetchall())
