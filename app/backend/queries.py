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


# ---------------------------------------------------------------- short-lived cache for the heavy page views
# The certified tables change only when the pipeline runs, so page views are cached for CACHE_TTL seconds. Anything that
# shows human actions (review queue, reviewed flags, activity) is invalidated whenever a review request is written.
import threading as _threading
import time as _time

CACHE_TTL = 600
_cache, _cache_lock = {}, _threading.Lock()


def cached(key: str, fn, ttl: int = CACHE_TTL):
    now = _time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = fn()
    with _cache_lock:
        _cache[key] = (now, value)
    return value


def invalidate_cache():
    with _cache_lock:
        _cache.clear()


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
    return cached("overview", _overview)


def _overview() -> dict:
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
    # Portfolio-wide credit risk (A09, A11): the same ECL the stress test and Monthly review use as their baseline.
    portfolio_risk_sql = f"""SELECT count_if(performance_status = 'Past Due' AND status = 'Active') AS past_due_projects,
       round(sum(current_disbursed_exposure_musd), 2) AS current_exposure_musd,
       round(sum(expected_credit_loss_musd), 2) AS expected_credit_loss_musd
FROM {P}"""
    return {"kpis": kpis, "status_mix": status, "alerts": {k: by_p.get(k, 0) for k in ("HIGH", "MEDIUM", "REVIEW")},
            "risk": q(risk_sql)[0], "portfolio_risk": q(portfolio_risk_sql)[0],
            "data_refreshed_at": data_refreshed_at(),
            "client_bands": try_q(f"SELECT band, count(*) AS clients FROM {T('certified_client_scorecard')} GROUP BY band"),
            "activity": activity(), "evidence": {"kpis": kpi_sql, "credit_risk": risk_sql,
                                                         "portfolio_credit_risk": portfolio_risk_sql}}


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


def _parts(reg: dict, question_id: str) -> list:
    """Register rows for one library question: the exact ID, or its parts (Q25 -> Q25a, Q25b, Q25c) for multi-part
    questions that 04_answers/ws1 certifies as separate queries."""
    if question_id in reg:
        return [reg[question_id]]
    return [reg[k] for k in sorted(reg) if k[:-1] == question_id and k[-1].isalpha()]


def answers_library() -> list:
    reg = {r["question_id"]: r for r in try_q(
        f"SELECT * FROM {T('answers_register')} WHERE workstream = 'WS1'")}
    out = []
    for item in LIBRARY:
        parts = _parts(reg, item["question_id"])
        r = parts[0] if parts else {}
        row = {**item, **{k: r.get(k) for k in (
            "sql_text", "assumptions", "assumption_ids", "row_count", "sensitivity_label", "rows_in_scope",
            "rows_needing_review", "rows_high_severity", "computed_at")},
            "certified": bool(parts) and all(p.get("sql_text") for p in parts)}
        if len(parts) > 1:
            row["sql_text"] = "\n\n".join(f"-- {p['question_id']}: {p['question']}\n{p['sql_text']}" for p in parts)
            row["part_ids"] = [p["question_id"] for p in parts]
        out.append(row)
    return out


def _decode(r: dict) -> dict:
    for k in ("result_preview_json", "sensitivity_preview_json"):
        try:
            r[k] = json.loads(r[k]) if r.get(k) else None
        except (TypeError, ValueError):
            r[k] = None
    return r


def certified_answer(question_id: str) -> dict:
    rows = try_q(f"SELECT * FROM {T('answers_register')} WHERE question_id = :qid OR question_id LIKE :pattern",
                 {"qid": question_id, "pattern": f"{question_id}_"})
    reg = {r["question_id"]: r for r in rows}
    parts = [_decode(p) for p in _parts(reg, question_id)]
    if not parts:
        return None
    meta = next((i for i in LIBRARY if i["question_id"] == question_id), {})
    if len(parts) == 1:
        return {**meta, **parts[0]}
    # Multi-part question: one certified query per part; each keeps its own SQL, result and data-quality counts.
    first = parts[0]
    ids = sorted({i for p in parts for i in (p.get("assumption_ids") or "").split(",") if i})
    return {**meta, **first, "question_id": question_id, "question": meta.get("question", first["question"]),
            "assumption_ids": ",".join(ids),
            "assumptions": " ".join(dict.fromkeys(p.get("assumptions") or "" for p in parts)).strip(),
            "sql_text": "\n\n".join(f"-- {p['question_id']}: {p['question']}\n{p['sql_text']}" for p in parts),
            "parts": [{k: p.get(k) for k in ("question_id", "question", "sql_text", "row_count", "result_preview_json",
                                             "rows_in_scope", "rows_needing_review", "rows_high_severity")}
                      for p in parts]}


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
    return cached("risk", _risk)


def _risk() -> dict:
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
       count_if(status = 'Dropped' AND is_monitored) AS dropped_but_monitored,
       count_if(status = 'Active' AND environmental_category = 'A') AS active_category_a,
       count_if(status = 'Active' AND environmental_category = 'A' AND performance_status = 'Performing') AS performing_category_a
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
            "context": {"active_category_a": int(c["active_category_a"]), "performing_category_a": int(c["performing_category_a"])},
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
    return cached("early_warning", _early_warning)


def _early_warning() -> dict:
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
    act = q(f"SELECT count_if(status = 'Active') AS n, count(DISTINCT CASE WHEN status = 'Active' THEN client_id END) AS clients FROM {P}")[0]
    active = int(act["n"])
    return {"alerts": alerts, "projects_to_review": int(q(projects_sql)[0]["projects"]), "active_projects": active,
            "clients_with_active_projects": int(act["clients"]),
            "signals": [{"column": c, "label": l, "clients": counts[c]} for c, l in SIGNALS],
            "evidence": {"alerts": alerts_sql, "projects": projects_sql}}


# ---------------------------------------------------------------- board briefing
def _review_owners():
    if get_settings().data_mode != "local":
        return q(f"""SELECT owner, count(*) AS projects FROM (
    SELECT trim(o) AS owner FROM {T('certified_investment_portfolio')}
    LATERAL VIEW explode(split(review_owners, ',')) t AS o WHERE needs_review) x
GROUP BY owner ORDER BY projects DESC""")
    return q(f"""SELECT owner, count(*) AS projects FROM (
    SELECT trim(unnest(string_split(review_owners, ','))) AS owner FROM {T('certified_investment_portfolio')} WHERE needs_review) x
WHERE owner <> '' GROUP BY owner ORDER BY projects DESC""")


def briefing() -> dict:
    out = dict(cached("briefing", _briefing))
    out["review_queue"] = review_queue()  # human actions: always fresh
    return out


def _briefing() -> dict:
    """Everything the Board briefing shows, fetched in parallel. The downside scenarios and the allocation view use the
    agents' deterministic engines (no language model), so the briefing gives the same figures every time."""
    from concurrent.futures import ThreadPoolExecutor

    from . import allocation, projects, stress

    jobs = {
        "overview": overview, "risk": risk, "recommendations": lambda: recommendations()["recommendations"],
        "early_warning": lambda: q(
            f"SELECT client_name, client_id, priority, triggered_by, suggested_action, exposure_affected_musd "
            f"FROM {T('certified_early_warning')} WHERE priority = 'HIGH' ORDER BY exposure_affected_musd DESC LIMIT 5"),
        "review_owners": _review_owners,
        "assumptions": lambda: try_q(f"SELECT assumption_id, topic, statement FROM {T('ref_assumptions')} ORDER BY assumption_id"),
        "strengths": lambda: _safe(projects.strengths),
        "allocation": lambda: _safe(allocation.allocation_summary),
        "scenario_watchlist": lambda: _safe(lambda: stress.run_scenario(migrate_watchlist=True, group_by="region",
                                                                        name="Every Watchlist project slips to default")),
        "scenario_rating": lambda: _safe(lambda: stress.run_scenario(min_rating=5, group_by="client",
                                                                     name="Every Active project rated 5-6 defaults")),
    }
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {k: ex.submit(f) for k, f in jobs.items()}
        out = {k: f.result() for k, f in futures.items()}
    rk = out["risk"]
    out["risk"] = {"summary": rk["summary"], "checks": rk["checks"], "context": rk.get("context")}
    for k in ("scenario_watchlist", "scenario_rating"):
        sc = out[k]
        if sc and not sc.get("error"):
            out[k] = {"name": sc["name"], "summary": sc["summary"], "breakdown": sc["breakdown"][:5],
                      "assumptions": sc["assumptions"], "sql": sc["sql"]}
    return out


def _safe(fn):
    """Optional briefing sections must not break the page (e.g. a table not yet built)."""
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def assumptions() -> list:
    return try_q(f"SELECT * FROM {T('ref_assumptions')} ORDER BY assumption_id")


# ---------------------------------------------------------------- human review log
def ensure_review_table():
    q(f"""CREATE TABLE IF NOT EXISTS {T('ops_review_requests')} (
  requested_at TIMESTAMP, requested_by STRING, entity_type STRING, entity_id STRING, entity_name STRING,
  action STRING, note STRING, source_page STRING)""")


def add_review_request(req: dict, user: str) -> dict:
    ensure_review_table()
    invalidate_cache()
    params = {"by": user, "etype": req["entity_type"], "eid": req["entity_id"], "ename": req.get("entity_name") or "",
              "action": req["action"], "note": req.get("note") or "", "page": req.get("source_page") or ""}
    q(f"""INSERT INTO {T('ops_review_requests')}
SELECT now(), :by, :etype, :eid, :ename, :action, :note, :page""", params)
    return {"ok": True}


def review_requests(limit: int = 50) -> list:
    return try_q(f"SELECT * FROM {T('ops_review_requests')} ORDER BY requested_at DESC LIMIT {int(limit)}")


def review_queue(limit: int = 30) -> dict:
    """Human-review queue: items flagged for review (agents' answers, clients, projects) and whether a reviewer has closed
    them since. A 'mark_reviewed' row closes every earlier flag on the same item; history is kept (append-only)."""
    sql = f"""WITH f AS (
  SELECT entity_type, entity_id, max_by(entity_name, requested_at) AS entity_name, max(requested_at) AS flagged_at,
         max_by(requested_by, requested_at) AS flagged_by, max_by(note, requested_at) AS note,
         max_by(source_page, requested_at) AS source_page, count(*) AS times_flagged
  FROM {T('ops_review_requests')} WHERE action = 'flag_for_review' GROUP BY entity_type, entity_id
), r AS (
  SELECT entity_type, entity_id, max(requested_at) AS reviewed_at, max_by(requested_by, requested_at) AS reviewed_by,
         max_by(note, requested_at) AS decision
  FROM {T('ops_review_requests')} WHERE action = 'mark_reviewed' GROUP BY entity_type, entity_id
)
SELECT f.*, r.reviewed_at, r.reviewed_by, r.decision,
       coalesce(r.reviewed_at >= f.flagged_at, false) AS is_reviewed
FROM f LEFT JOIN r ON f.entity_type = r.entity_type AND f.entity_id = r.entity_id
ORDER BY is_reviewed, f.flagged_at DESC
LIMIT {int(limit)}"""
    rows = try_q(sql)
    for r in rows:
        for k in ("flagged_at", "reviewed_at"):
            if r.get(k) is not None:
                r[k] = str(r[k])
    return {"items": rows, "open": sum(1 for r in rows if not r.get("is_reviewed")), "sql": sql}


# ---------------------------------------------------------------- Genie question history
# Every Genie answer is stored as it was shown (text, SQL, result rows, trust check), so History reopens it without
# asking Genie again or re-running the SQL.
def ensure_genie_history_table():
    q(f"""CREATE TABLE IF NOT EXISTS {T('ops_genie_history')} (
  history_id STRING, asked_at TIMESTAMP, asked_by STRING, question STRING, status STRING,
  trust_level STRING, row_count BIGINT, response_json STRING)
COMMENT 'Genie questions and the answers shown in the app, stored as returned (History reopens them without re-running).'""")


def save_genie_answer(question: str, response: dict, user: str) -> str:
    import uuid
    hid = uuid.uuid4().hex
    try:
        ensure_genie_history_table()
        q(f"""INSERT INTO {T('ops_genie_history')}
SELECT :hid, now(), :by, :question, :status, :level, CAST(:rows AS BIGINT), :resp""",
          {"hid": hid, "by": user, "question": question, "status": response.get("status") or "",
           "level": (response.get("trust") or {}).get("level") or "", "rows": int(response.get("row_count") or 0),
           "resp": json.dumps(response, default=str)})
    except Exception:
        return None  # history is best effort: never block the answer
    return hid


def genie_history(limit: int = 100) -> list:
    return try_q(f"""SELECT history_id, CAST(asked_at AS STRING) AS asked_at, asked_by, question, status, trust_level, row_count
FROM {T('ops_genie_history')} ORDER BY asked_at DESC LIMIT {int(limit)}""")


def genie_history_item(history_id: str):
    rows = try_q(f"SELECT question, CAST(asked_at AS STRING) AS asked_at, asked_by, response_json FROM {T('ops_genie_history')} WHERE history_id = :hid",
                 {"hid": history_id})
    if not rows:
        return None
    r = rows[0]
    return {"question": r["question"], "asked_at": r["asked_at"], "asked_by": r["asked_by"],
            "result": json.loads(r["response_json"] or "{}")}
