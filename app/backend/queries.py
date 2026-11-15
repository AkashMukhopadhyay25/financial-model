"""
Every figure the app shows comes from one of these queries on the certified tables. The SQL text is returned with
the data, so each page can show its own evidence. Definitions follow ref_assumptions (A01-A22): projects are counted
by project_url (A01), totals use the Board-approved amount (A08), no status filter unless chosen (A03).
"""
import json
from difflib import SequenceMatcher
from pathlib import Path

from .settings import get_settings
from .sql import get_db

LIBRARY = json.loads((Path(__file__).with_name("question_library.json")).read_text(encoding="utf-8"))
FILTER_COLUMNS = {  # query-string name -> column
    "region": "region", "country": "country", "industry": "industry", "department": "department",
    "product_line": "product_line", "status": "status", "year": "approval_year",
}
SEVERITY_ORDER = "CASE priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END"
# Early-warning signal columns and labels; same as 00_setup/portfolio_sql.py (A22), which builds the table.
SIGNALS = [("sig_multiple_watchlist", "Multiple Watchlist projects"), ("sig_high_risk_rating", "Internal risk ratings 5-6"),
           ("sig_review_overdue", "Long time since last review"), ("sig_existing_past_due", "Existing Past Due projects"),
           ("sig_country_concentration", "Concentration in one country")]


def T(name: str) -> str:
    return get_settings().table(name)


def q(sql: str, params: dict = None) -> list:
    return get_db().query(sql, params)


def try_q(sql: str, params: dict = None, default=None):
    """For optional tables (ops_*): a missing table must not break a page."""
    try:
        return q(sql, params)
    except Exception:
        return default if default is not None else []


def _literal(v) -> str:
    return str(v) if isinstance(v, (int, float)) else "'" + str(v).replace("'", "''") + "'"


def render(sql: str, params: dict) -> str:
    """SQL with parameter values written in, for display as evidence only (never executed)."""
    for k, v in sorted((params or {}).items(), key=lambda kv: -len(kv[0])):
        sql = sql.replace(f":{k}", _literal(v))
    return sql.strip()


# ---------------------------------------------------------------- shared
def portfolio_where(filters: dict) -> tuple:
    clauses, params = [], {}
    for key, col in FILTER_COLUMNS.items():
        v = (filters or {}).get(key)
        if v in (None, "", "All"):
            continue
        if key == "year":
            clauses.append(f"{col} = CAST(:{key} AS INT)")
        else:
            clauses.append(f"{col} = :{key}")
        params[key] = v
    return (" AND ".join(clauses) or "TRUE"), params


def dq_scope(where: str, params: dict) -> dict:
    r = q(f"""SELECT count(*) AS rows_in_scope, count_if(needs_review) AS rows_needing_review,
                     count_if(dq_max_severity = 'high') AS rows_high_severity
              FROM {T('certified_investment_portfolio')} WHERE {where}""", params)[0]
    return {k: int(v or 0) for k, v in r.items()}


# ---------------------------------------------------------------- overview
def overview() -> dict:
    P = T("certified_investment_portfolio")
    kpi_sql = f"""SELECT count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd,
       count(DISTINCT client_id) AS clients, count_if(status = 'Active') AS active_projects,
       max(reporting_date) AS reporting_date, count_if(needs_review) AS projects_needing_review,
       count_if(dq_max_severity = 'high') AS projects_high_severity
FROM {P}"""
    kpis = q(kpi_sql)[0]
    status = q(f"SELECT status, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd FROM {P} "
               "GROUP BY status ORDER BY projects DESC")
    alerts = q(f"SELECT priority, count(*) AS clients FROM {T('certified_early_warning')} GROUP BY priority")
    by_p = {a["priority"]: int(a["clients"]) for a in alerts}
    # Credit risk at a glance: the WS2 Board figures (same scope and measures as the certified WS2 answers)
    risk_sql = f"""SELECT count(*) AS projects, count(DISTINCT client_id) AS clients,
       round(sum(CASE WHEN performance_status = 'Past Due' THEN disbursed_musd ELSE 0 END), 2) AS past_due_disbursed_musd,
       round(sum(CASE WHEN performance_status = 'Watchlist' THEN disbursed_musd ELSE 0 END), 2) AS watchlist_disbursed_musd,
       round(sum(expected_credit_loss_musd), 2) AS expected_credit_loss_musd
FROM {P}
WHERE {WS2_SCOPE}"""
    return {"kpis": kpis, "status_mix": status, "alerts": {k: by_p.get(k, 0) for k in ("HIGH", "MEDIUM", "REVIEW")},
            "risk": q(risk_sql)[0],
            "data_refreshed_at": data_refreshed_at(),
            "client_bands": try_q(f"SELECT band, count(*) AS clients FROM {T('certified_client_scorecard')} GROUP BY band"),
            "activity": activity(), "evidence": {"kpis": kpi_sql, "credit_risk": risk_sql}}


def data_refreshed_at():
    """When portfolio data was last loaded (ops_raw_load_log); the local preview uses its build time."""
    for sql in (f"SELECT max(loaded_at) AS at FROM {T('ops_raw_load_log')}",
                f"SELECT max(built_at) AS at FROM {T('ops_preview_info')}"):
        r = try_q(sql)
        if r and r[0].get("at"):
            return str(r[0]["at"])
    return None


def activity() -> list:
    """Recent events from the operational logs (each table optional)."""
    items = []
    for sql, label in [
        (f"SELECT max(loaded_at) AS at FROM {T('ops_raw_load_log')}", "Portfolio data refreshed"),
        (f"SELECT max(run_at) AS at FROM {T('ops_dq_checks')}", "Data-quality checks completed"),
        (f"SELECT max(computed_at) AS at FROM {T('answers_register')}", "Certified answers updated"),
        (f"SELECT max(generated_at) AS at FROM {T('ws3_recommendations')}", "Board recommendation draft updated"),
        (f"SELECT max(requested_at) AS at FROM {T('ops_review_requests')}", "Human review requested"),
        (f"SELECT max(built_at) AS at FROM {T('ops_preview_info')}", "Local preview database built"),
    ]:
        r = try_q(sql)
        if r and r[0].get("at"):
            items.append({"label": label, "at": str(r[0]["at"])})
    return sorted(items, key=lambda i: i["at"], reverse=True)[:4]


# ---------------------------------------------------------------- WS1 portfolio analytics
def filter_options() -> dict:
    P = T("certified_investment_portfolio")
    out = {}
    for key, col in FILTER_COLUMNS.items():
        rows = q(f"SELECT DISTINCT {col} AS v FROM {P} WHERE {col} IS NOT NULL ORDER BY v")
        out[key] = [r["v"] for r in rows]
    return out


def portfolio(filters: dict) -> dict:
    P = T("certified_investment_portfolio")
    where, params = portfolio_where(filters)
    kpi_sql = f"""SELECT count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd,
       count_if(status = 'Active') AS active_projects, count(DISTINCT client_id) AS clients,
       max(reporting_date) AS reporting_date
FROM {P}
WHERE {where}"""
    region_sql = f"""SELECT region, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd
FROM {P}
WHERE {where}
GROUP BY region
ORDER BY approved_musd DESC"""
    trend_sql = f"""SELECT approval_year AS year, count(*) AS projects, count_if(status = 'Active') AS active_projects,
       round(sum(total_approved_musd), 2) AS approved_musd
FROM {P}
WHERE {where} AND approval_year IS NOT NULL
GROUP BY approval_year
ORDER BY approval_year"""
    table_sql = f"""SELECT project_name, project_url, region, country, product_line, industry, status,
       round(total_approved_musd, 2) AS approved_musd, needs_review, dq_max_severity, dq_flag_ids, dq_messages
FROM {P}
WHERE {where}
ORDER BY total_approved_musd DESC
LIMIT 25"""
    return {
        "kpis": q(kpi_sql, params)[0],
        "by_region": q(region_sql, params),
        "trend": q(trend_sql, params),
        "projects": q(table_sql, params),
        "data_quality": dq_scope(where, params),
        "filters_applied": {k: v for k, v in params.items()},
        "evidence": {"kpis": render(kpi_sql, params), "by_region": render(region_sql, params),
                     "trend": render(trend_sql, params), "projects": render(table_sql, params)},
        "assumption_ids": ["A01", "A03", "A08"],
    }


def answers_library() -> list:
    reg = {r["question_id"]: r for r in try_q(
        f"SELECT * FROM {T('answers_register')} WHERE workstream = 'WS1'")}
    out = []
    for item in LIBRARY:
        r = reg.get(item["question_id"], {})
        out.append({**item, **{k: r.get(k) for k in (
            "sql_text", "assumptions", "assumption_ids", "row_count", "sensitivity_label", "rows_in_scope",
            "rows_needing_review", "rows_high_severity", "computed_at")}, "certified": bool(r.get("sql_text"))})
    return out


def certified_answer(question_id: str) -> dict:
    rows = try_q(f"SELECT * FROM {T('answers_register')} WHERE question_id = :qid", {"qid": question_id})
    if not rows:
        return None
    r = rows[0]
    for k in ("result_preview_json", "sensitivity_preview_json"):
        try:
            r[k] = json.loads(r[k]) if r.get(k) else None
        except (TypeError, ValueError):
            r[k] = None
    meta = next((i for i in LIBRARY if i["question_id"] == question_id), {})
    return {**meta, **r}


def _norm(s: str) -> str:
    return " ".join("".join(c.lower() if c.isalnum() else " " for c in s).split())


def match_certified(question: str, threshold: float = 0.72):
    """Closest WS1 question by wording; used to show the certified answer next to Genie's."""
    best, score = None, 0.0
    for item in LIBRARY:
        s = SequenceMatcher(None, _norm(question), _norm(item["question"])).ratio()
        if s > score:
            best, score = item, s
    return {"question_id": best["question_id"], "question": best["question"], "similarity": round(score, 2)} \
        if best and score >= threshold else None


# ---------------------------------------------------------------- WS2 risk & exposure
WS2_SCOPE = "environmental_category = 'A' AND performance_status IN ('Past Due', 'Watchlist')"


def risk() -> dict:
    P = T("certified_investment_portfolio")
    summary_sql = f"""SELECT coalesce(performance_status, 'TOTAL') AS status_label,
       count(*) AS projects,
       count(DISTINCT client_id) AS clients,
       round(sum(total_approved_musd), 2) AS approved_musd,
       round(sum(disbursed_musd), 2) AS disbursed_capital_tied_up_musd,
       round(sum(undisbursed_commitment_musd), 2) AS undisbursed_commitment_musd,
       round(sum(expected_credit_loss_musd), 2) AS expected_credit_loss_musd
FROM {P}
WHERE {WS2_SCOPE}
GROUP BY ROLLUP(performance_status)
ORDER BY status_label = 'TOTAL', status_label"""
    projects_sql = f"""SELECT project_name, project_url, project_number, client_name, client_id, country, region, industry,
       environmental_category, performance_status, internal_risk_rating, status,
       round(total_approved_musd, 2) AS approved_musd, round(disbursed_musd, 2) AS disbursed_musd,
       round(expected_credit_loss_musd, 2) AS expected_credit_loss_musd, days_since_last_review,
       mon_flag_review_overdue AS review_overdue, needs_review, dq_max_severity, dq_flag_ids, dq_messages
FROM {P}
WHERE {WS2_SCOPE}
ORDER BY performance_status, total_approved_musd DESC"""
    checks_sql = f"""SELECT count(*) AS projects, count(DISTINCT project_url) AS distinct_urls,
       count_if(status <> 'Dropped') AS non_dropped, count_if(status <> 'Dropped' AND NOT is_monitored) AS missing_monitoring,
       count_if(status = 'Dropped' AND is_monitored) AS dropped_but_monitored
FROM {P}"""
    summary = q(summary_sql)
    c = q(checks_sql)[0]
    asm = {r["assumption_id"] for r in try_q(f"SELECT assumption_id FROM {T('ref_assumptions')}")}
    needed = {"A01", "A09", "A10", "A11", "A17"}
    checks = [
        {"name": "Join logic", "ok": True,
         "detail": "Projects joined to monitoring on project_url (A01). Project Number is not unique and is never used to join."},
        {"name": "Definitions", "ok": True,
         "detail": "Approved = Board total; disbursed = monitoring amount; ECL = 60% of disbursed on Past Due only (A11)."},
        {"name": "Assumptions", "ok": needed <= asm,
         "detail": f"Uses {', '.join(sorted(needed))}" + ("" if needed <= asm else " (missing from ref_assumptions)")},
        {"name": "Missing records", "ok": int(c["missing_monitoring"]) == 0 and int(c["dropped_but_monitored"]) == 0,
         "detail": f"{c['missing_monitoring']} non-Dropped projects without monitoring; {c['dropped_but_monitored']} Dropped projects monitored."},
        {"name": "Duplicate checks", "ok": int(c["projects"]) == int(c["distinct_urls"]),
         "detail": f"{c['projects']:,} rows, {c['distinct_urls']:,} distinct project URLs."},
    ]
    register = try_q(f"SELECT question_id, question, sql_text, assumptions, assumption_ids, computed_at "
                     f"FROM {T('answers_register')} WHERE workstream = 'WS2' ORDER BY question_id")
    return {"summary": summary, "projects": q(projects_sql), "checks": checks, "register": register,
            "data_quality": dq_scope(WS2_SCOPE, {}),
            "ecl_loss_rate": get_settings().ecl_loss_rate,
            "evidence": {"summary": summary_sql, "projects": projects_sql, "checks": checks_sql}}


# ---------------------------------------------------------------- WS3 client intelligence
CLIENT_LIST_COLS = """client_id, client_name, primary_industry, primary_region, band, health_score, n_projects, n_active,
       n_past_due, n_watchlist, approved_musd, current_disbursed_exposure_musd, undisbursed_commitment_musd,
       exposure_affected_musd, expected_credit_loss_musd, exposure_weighted_risk_rating, band_evidence,
       n_review_overdue_active, n_projects_needing_review"""


def clients(search: str = "", band: str = "", limit: int = 50) -> dict:
    where, params = ["TRUE"], {}
    if search:
        where.append("(lower(client_name) LIKE :s OR lower(client_id) LIKE :s)")
        params["s"] = f"%{search.lower()}%"
    if band:
        where.append("band = :band")
        params["band"] = band
    sql = f"""SELECT {CLIENT_LIST_COLS}
FROM {T('certified_client_scorecard')}
WHERE {' AND '.join(where)}
ORDER BY exposure_affected_musd DESC
LIMIT {int(limit)}"""
    bands = q(f"""SELECT band, count(*) AS clients, round(sum(exposure_affected_musd), 2) AS exposure_affected_musd
FROM {T('certified_client_scorecard')} GROUP BY band ORDER BY band""")
    return {"clients": q(sql, params), "bands": bands, "evidence": render(sql, params)}


def recommendations() -> dict:
    sql = f"""SELECT r.recommendation, r.client_id, r.client_name, r.primary_industry, r.primary_region,
       r.current_disbursed_exposure_musd, r.undisbursed_commitment_musd, r.exposure_affected_musd,
       r.expected_credit_loss_musd, r.health_score, r.evidence_summary, r.suggested_action, r.team_rationale,
       r.review_owner, s.band, s.n_active, s.n_past_due, s.n_watchlist
FROM {T('ws3_recommendations')} r
LEFT JOIN {T('certified_client_scorecard')} s ON r.client_id = s.client_id
ORDER BY r.recommendation, r.exposure_affected_musd DESC"""
    return {"recommendations": q(sql), "evidence": sql}


def client_detail(client_id: str) -> dict:
    P, params = T("certified_investment_portfolio"), {"cid": client_id}
    sc = q(f"SELECT * FROM {T('certified_client_scorecard')} WHERE client_id = :cid", params)
    if not sc:
        return None
    projects_sql = f"""SELECT project_name, project_url, project_number, country, region, industry, product_line, status,
       performance_status, risk_flag, internal_risk_rating, environmental_category, is_climate_related,
       round(total_approved_musd, 2) AS approved_musd, round(disbursed_musd, 2) AS disbursed_musd,
       round(current_disbursed_exposure_musd, 2) AS current_exposure_musd,
       round(undisbursed_commitment_musd, 2) AS undisbursed_musd, days_since_last_review,
       mon_flag_review_overdue AS review_overdue, needs_review, dq_max_severity, dq_flag_ids, dq_messages
FROM {P}
WHERE client_id = :cid
ORDER BY CASE risk_flag WHEN 'RED' THEN 1 WHEN 'AMBER' THEN 2 ELSE 3 END, total_approved_musd DESC"""

    def mix(col):
        return q(f"SELECT {col} AS label, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd "
                 f"FROM {P} WHERE client_id = :cid GROUP BY {col} ORDER BY projects DESC", params)

    ew = try_q(f"SELECT * FROM {T('certified_early_warning')} WHERE client_id = :cid", params)
    rec = try_q(f"SELECT recommendation, suggested_action, team_rationale FROM {T('ws3_recommendations')} "
                "WHERE client_id = :cid", params)
    return {"scorecard": sc[0], "projects": q(projects_sql, params),
            "mix": {"status": mix("status"), "performance": mix("performance_status"), "product": mix("product_line"),
                    "rating": mix("internal_risk_rating"), "country": mix("country"), "climate": mix("is_climate_related")},
            "early_warning": ew[0] if ew else None, "recommendation": rec[0] if rec else None,
            "evidence": render(projects_sql, params)}


def compare(ids: list) -> list:
    if not ids:
        return []
    params = {f"c{i}": v for i, v in enumerate(ids[:4])}
    return q(f"SELECT {CLIENT_LIST_COLS}, closed_loss_rate, distress_share, top_country, top_country_exposure_share, "
             f"n_active_rating_5_6 FROM {T('certified_client_scorecard')} "
             f"WHERE client_id IN ({', '.join(':' + k for k in params)})", params)


# ---------------------------------------------------------------- early warning
def early_warning() -> dict:
    EW, P = T("certified_early_warning"), T("certified_investment_portfolio")
    alerts_sql = f"""SELECT *
FROM {EW}
ORDER BY {SEVERITY_ORDER}, exposure_affected_musd DESC"""
    projects_sql = f"""SELECT count(*) AS projects
FROM {P} p
JOIN {EW} e ON p.client_id = e.client_id
WHERE p.status = 'Active'
  AND (p.performance_status IN ('Watchlist', 'Past Due') OR p.internal_risk_rating >= 5 OR p.mon_flag_review_overdue)"""
    alerts = q(alerts_sql)
    reviewed = {r["entity_id"]: r for r in try_q(
        f"""SELECT entity_id, max(requested_at) AS reviewed_at FROM {T('ops_review_requests')}
            WHERE entity_type = 'client' AND action = 'mark_reviewed' GROUP BY entity_id""")}
    for a in alerts:
        a["reviewed_at"] = str(reviewed[a["client_id"]]["reviewed_at"]) if a["client_id"] in reviewed else None
    counts = {col: sum(1 for a in alerts if a.get(col)) for col, _ in SIGNALS}
    active = int(q(f"SELECT count_if(status = 'Active') AS n FROM {P}")[0]["n"])
    return {"alerts": alerts, "projects_to_review": int(q(projects_sql)[0]["projects"]), "active_projects": active,
            "signals": [{"column": c, "label": l, "clients": counts[c]} for c, l in SIGNALS],
            "evidence": {"alerts": alerts_sql, "projects": projects_sql}}


# ---------------------------------------------------------------- board briefing
def briefing() -> dict:
    ov = overview()
    rk = risk()
    rec = recommendations()["recommendations"]
    ew = q(f"SELECT client_name, client_id, priority, triggered_by, suggested_action, exposure_affected_musd "
           f"FROM {T('certified_early_warning')} WHERE priority = 'HIGH' ORDER BY exposure_affected_musd DESC LIMIT 5")
    owners = q(f"""SELECT owner, count(*) AS projects FROM (
    SELECT trim(o) AS owner FROM {T('certified_investment_portfolio')}
    LATERAL VIEW explode(split(review_owners, ',')) t AS o WHERE needs_review) x
GROUP BY owner ORDER BY projects DESC""") if get_settings().data_mode != "local" else q(
        f"""SELECT owner, count(*) AS projects FROM (
    SELECT trim(unnest(string_split(review_owners, ','))) AS owner FROM {T('certified_investment_portfolio')} WHERE needs_review) x
WHERE owner <> '' GROUP BY owner ORDER BY projects DESC""")
    assumptions = try_q(f"SELECT assumption_id, topic, statement FROM {T('ref_assumptions')} ORDER BY assumption_id")
    return {"overview": ov, "risk": {"summary": rk["summary"], "checks": rk["checks"]}, "recommendations": rec,
            "early_warning": ew, "review_owners": owners, "assumptions": assumptions}


def assumptions() -> list:
    return try_q(f"SELECT * FROM {T('ref_assumptions')} ORDER BY assumption_id")


# ---------------------------------------------------------------- human review log
def ensure_review_table():
    q(f"""CREATE TABLE IF NOT EXISTS {T('ops_review_requests')} (
  requested_at TIMESTAMP, requested_by STRING, entity_type STRING, entity_id STRING, entity_name STRING,
  action STRING, note STRING, source_page STRING)""")


def add_review_request(req: dict, user: str) -> dict:
    ensure_review_table()
    params = {"by": user, "etype": req["entity_type"], "eid": req["entity_id"], "ename": req.get("entity_name") or "",
              "action": req["action"], "note": req.get("note") or "", "page": req.get("source_page") or ""}
    q(f"""INSERT INTO {T('ops_review_requests')}
SELECT now(), :by, :etype, :eid, :ename, :action, :note, :page""", params)
    return {"ok": True}


def review_requests(limit: int = 50) -> list:
    return try_q(f"SELECT * FROM {T('ops_review_requests')} ORDER BY requested_at DESC LIMIT {int(limit)}")
