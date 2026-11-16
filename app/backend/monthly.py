"""
Monthly history: trends across reporting months and loading a new month.

Tables come from 01_data/run_monthly_pipeline (08_trends), in the monthly schema (IFC_MONTHLY_SCHEMA, default
portfolio_monthly_dev): kpi_monthly, compare_months(), project_month_changes, ops_monthly_loads, ops_schema_gate_log.
Uploads go to that schema's landing volume, incoming/YYYY-MM/, and start the run_monthly_pipeline job (IFC_MONTHLY_JOB_ID).
"""
import base64
import io
import os
import re

from .settings import get_settings
from .sql import get_db

MONTH_RE = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")
FILE_PATTERNS = [re.compile(r"^synthetic_ifc_projects_.*\.csv$"), re.compile(r"^synthetic_project_monitoring.*\.csv$")]
DIMENSIONS = ["Portfolio", "Region", "Industry", "Product line", "Department"]


def schema() -> str:
    return os.getenv("IFC_MONTHLY_SCHEMA") or "portfolio_monthly_dev"


def M(name: str) -> str:
    return f"{get_settings().catalog}.{schema()}.{name}"


def job_id() -> str:
    return os.getenv("IFC_MONTHLY_JOB_ID") or ""


def q(sql: str, params: dict = None) -> list:
    return get_db().query(sql, params)


def try_q(sql: str, params: dict = None) -> list:
    try:
        return q(sql, params)
    except Exception:
        return []


def status() -> dict:
    months_sql = f"SELECT DISTINCT month_label FROM {M('kpi_monthly')} ORDER BY month_label"
    loads_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, source, source_file, rows_loaded,
       CAST(loaded_at AS STRING) AS loaded_at, is_active
FROM {M('ops_monthly_loads')}
ORDER BY reporting_month DESC, loaded_at DESC"""
    gate_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, file_name, source, status, messages,
       CAST(checked_at AS STRING) AS checked_at
FROM {M('ops_schema_gate_log')}
ORDER BY checked_at DESC LIMIT 20"""
    return {"schema": f"{get_settings().catalog}.{schema()}", "months": [r["month_label"] for r in try_q(months_sql)],
            "loads": try_q(loads_sql), "gate": try_q(gate_sql), "job_configured": bool(job_id()),
            "dimensions": DIMENSIONS, "evidence": {"months": months_sql, "loads": loads_sql, "gate": gate_sql}}


def compare(month_a: str, month_b: str, dimension: str) -> dict:
    if not (MONTH_RE.match(month_a) and MONTH_RE.match(month_b)) or dimension not in DIMENSIONS:
        raise ValueError("Months must look like 2026-10 and the breakdown must be one of " + ", ".join(DIMENSIONS))
    sql = f"SELECT * FROM {M('compare_months')}(:month_a, :month_b, :dimension)"
    rows = q(sql, {"month_a": month_a, "month_b": month_b, "dimension": dimension})
    shown = sql.replace(":month_a", f"'{month_a}'").replace(":month_b", f"'{month_b}'").replace(":dimension", f"'{dimension}'")
    return {"rows": rows, "evidence": shown}


def series() -> dict:
    sql = f"""SELECT month_label, kpi_id, kpi_name, category, unit, better, value
FROM {M('kpi_monthly')}
WHERE dimension = 'Portfolio'
ORDER BY kpi_id, month_label"""
    return {"rows": q(sql), "evidence": sql}


def changes(month_a: str, month_b: str, change_type: str = "") -> dict:
    if not (MONTH_RE.match(month_a) and MONTH_RE.match(month_b)):
        raise ValueError("Months must look like 2026-10")
    where = "date_format(reporting_month, 'yyyy-MM') > :month_a AND date_format(reporting_month, 'yyyy-MM') <= :month_b"
    params = {"month_a": month_a, "month_b": month_b}
    summary_sql = f"""SELECT change_type, impact, count(*) AS projects, round(sum(amount_musd), 1) AS amount_musd
FROM {M('project_month_changes')}
WHERE {where}
GROUP BY change_type, impact
ORDER BY projects DESC"""
    out = {"summary": q(summary_sql, params), "evidence": summary_sql}
    if change_type:
        detail_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, client_name, project_name, region, industry,
       from_value, to_value, round(amount_musd, 2) AS amount_musd
FROM {M('project_month_changes')}
WHERE {where} AND change_type = :change_type
ORDER BY abs(amount_musd) DESC NULLS LAST
LIMIT 200"""
        out["detail"] = q(detail_sql, {**params, "change_type": change_type})
        out["detail_evidence"] = detail_sql
    return out


def upload(month: str, files: list) -> dict:
    """files: [{name, content_base64}]. Writes to incoming/<month>/ and starts the monthly pipeline job."""
    from databricks.sdk import WorkspaceClient

    if not MONTH_RE.match(month or ""):
        raise ValueError("Month must look like 2026-11")
    if not files:
        raise ValueError("Add the month's CSV files")
    bad = [f["name"] for f in files if not any(p.match(f["name"]) for p in FILE_PATTERNS)]
    if bad:
        raise ValueError(f"Unrecognised file name(s): {', '.join(bad)}. Expected synthetic_ifc_projects_*.csv "
                         "or synthetic_project_monitoring*.csv")
    already = any(r["month"] == month for r in try_q(
        f"SELECT DISTINCT date_format(reporting_month, 'yyyy-MM') AS month FROM {M('ops_monthly_loads')}"))
    w = WorkspaceClient()
    root = f"/Volumes/{get_settings().catalog}/{schema()}/landing/incoming/{month}"
    for f in files:
        w.files.upload(f"{root}/{f['name']}", io.BytesIO(base64.b64decode(f["content_base64"])), overwrite=True)
    run_id = None
    if job_id():
        run_id = w.jobs.run_now(job_id=int(job_id())).run_id
    return {"uploaded": [f["name"] for f in files], "folder": root, "replaces_existing_month": already,
            "run_id": run_id, "job_configured": bool(job_id())}


def runs() -> list:
    if not job_id():
        return []
    from databricks.sdk import WorkspaceClient

    out = []
    for r in WorkspaceClient().jobs.list_runs(job_id=int(job_id()), limit=5):
        st = r.state
        state = ""
        if st:
            state = (st.result_state.value if st.result_state else st.life_cycle_state.value if st.life_cycle_state else "")
        out.append({"run_id": r.run_id, "started_ms": r.start_time, "state": state,
                    "message": st.state_message if st else "", "url": r.run_page_url})
    return out


# ---------------------------------------------------------------- monthly review (client-centred)
HIST = "certified_investment_portfolio_history"
CREDIT_NEG = {"PERFORMANCE_WORSENED", "RISK_DOWNGRADE"}
CREDIT_POS = {"PERFORMANCE_IMPROVED", "RISK_UPGRADE"}
GROWTH = {"NEW_PROJECT", "BOARD_APPROVED", "SIGNED", "FIRST_DISBURSEMENT"}
MATERIAL = CREDIT_NEG | CREDIT_POS | GROWTH | {"STATUS_CHANGE"}
HEADLINE_KPIS = ["R01", "R02", "R04", "M01"]
SEVERITY = {"PERFORMANCE_WORSENED": 1, "RISK_DOWNGRADE": 2, "STATUS_CHANGE": 3, "PERFORMANCE_IMPROVED": 4, "RISK_UPGRADE": 5,
            "BOARD_APPROVED": 6, "SIGNED": 7, "FIRST_DISBURSEMENT": 7, "NEW_PROJECT": 8}


def month_name(m: str) -> str:
    import calendar
    return f"{calendar.month_name[int(m[5:7])]} {m[:4]}" if m else ""


def _money(v) -> str:
    v = float(v or 0)
    return f"${v / 1000:,.2f}B" if abs(v) >= 1000 else f"${v:,.0f}M"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _amt(rows) -> float:
    return sum(float(e.get("amount_musd") or 0) for e in rows)


def describe(e: dict) -> str:
    """One plain-English sentence for a project change."""
    t, f, to = e["change_type"], e.get("from_value"), e.get("to_value")
    texts = {
        "PERFORMANCE_WORSENED": f"Repayment status moved from {f or 'Performing'} to {to}",
        "PERFORMANCE_IMPROVED": f"Repayment status recovered from {f} to {to}",
        "RISK_DOWNGRADE": f"Internal risk rating worsened from {f} to {to}",
        "RISK_UPGRADE": f"Internal risk rating improved from {f} to {to}",
        "NEW_PROJECT": "New project added to the pipeline",
        "BOARD_APPROVED": "Approved by the Board",
        "SIGNED": "Investment agreement signed",
        "FIRST_DISBURSEMENT": "First disbursement made",
        "STATUS_CHANGE": f"Project status changed from {f} to {to}",
        "DISBURSED": f"Further disbursement of {_money(e.get('amount_musd'))}",
        "REVIEW_OVERDUE": f"Monitoring review now overdue ({to} days since the last review)",
        "REVIEW_OVERDUE_CLEARED": "Overdue monitoring review completed",
    }
    return texts.get(t, t.replace("_", " ").capitalize())


def _months() -> list:
    return [r["month_label"] for r in try_q(f"SELECT DISTINCT month_label FROM {M('kpi_monthly')} ORDER BY month_label")]


def review(month: str = "") -> dict:
    months = _months()
    if len(months) < 2:
        return {"months": months, "ready": False}
    month = month if month in months[1:] else months[-1]
    prev = months[months.index(month) - 1]
    p = {"m": month}

    kpi_sql = f"""SELECT kpi_id, kpi_name, unit, better, previous_value, value, change, change_pct, assessment
FROM {M('kpi_month_over_month')}
WHERE dimension = 'Portfolio' AND month_label = :m"""
    kpis = {r["kpi_id"]: r for r in q(kpi_sql, p)}
    events_sql = f"""SELECT client_name, project_name, region, industry, change_type, impact, from_value, to_value, amount_musd
FROM {M('project_month_changes')}
WHERE date_format(reporting_month, 'yyyy-MM') = :m"""
    events = q(events_sql, p)
    ids_sql = f"""SELECT client_name, max(client_id) AS client_id
FROM {M(HIST)} WHERE date_format(reporting_month, 'yyyy-MM') = :m GROUP BY client_name"""
    ids = {r["client_name"]: r["client_id"] for r in q(ids_sql, p)}

    clients = {}
    for e in events:
        t = e["change_type"]
        if t not in MATERIAL:
            continue
        c = clients.setdefault(e["client_name"], {
            "client_name": e["client_name"], "client_id": ids.get(e["client_name"]), "neg": 0, "pos": 0, "growth": 0,
            "to_past_due": 0, "to_watchlist": 0, "downgrades": 0, "recoveries": 0, "exposure_musd": 0.0,
            "approved_musd": 0.0, "events": [], "_proj": set()})
        if t in CREDIT_NEG or (t == "STATUS_CHANGE" and e.get("to_value") == "Dropped"):
            c["neg"] += 1
            if t == "PERFORMANCE_WORSENED":
                c["to_past_due" if e["to_value"] == "Past Due" else "to_watchlist"] += 1
            elif t == "RISK_DOWNGRADE":
                c["downgrades"] += 1
        elif t in CREDIT_POS:
            c["pos"] += 1
            c["recoveries"] += 1
        else:
            c["growth"] += 1
            if t == "BOARD_APPROVED":
                c["approved_musd"] += float(e["amount_musd"] or 0)
        if (t in CREDIT_NEG or t in CREDIT_POS) and e["project_name"] not in c["_proj"]:
            c["_proj"].add(e["project_name"])
            c["exposure_musd"] += float(e["amount_musd"] or 0)
        c["events"].append({"project_name": e["project_name"], "text": describe(e), "impact": e["impact"],
                            "rank": SEVERITY.get(t, 9) - (1 if e.get("to_value") == "Past Due" else 0)})

    rank = {"Deteriorated": 0, "Mixed": 1, "Improved": 2, "New business": 3}
    out = []
    for c in clients.values():
        c.pop("_proj")
        c["events"].sort(key=lambda ev: ev["rank"])
        c["direction"] = ("Deteriorated" if c["neg"] > c["pos"] else "Improved" if c["pos"] > c["neg"]
                          else "Mixed" if c["neg"] else "New business")
        want = "Positive" if c["direction"] in ("Improved", "New business") else "Negative"
        first = next((ev for ev in c["events"] if ev["impact"] == want), c["events"][0])
        c["headline"] = f"{first['project_name']}: {first['text'][0].lower()}{first['text'][1:]}"
        out.append(c)
    out.sort(key=lambda c: (rank[c["direction"]], -c["exposure_musd"], -c["approved_musd"]))

    return {"ready": True, "months": months, "month": month, "previous": prev, "month_name": month_name(month),
            "previous_name": month_name(prev), "total_clients": len(ids), "changed_clients": len(out),
            "counts": {d: sum(1 for c in out if c["direction"] == d) for d in rank},
            "kpis": [kpis[k] for k in HEADLINE_KPIS if k in kpis], "clients": out,
            **_narrative(kpis, events, out, prev),
            "balance": _balance(events), "actions": _actions(kpis, events, out),
            "evidence": {"measures": kpi_sql.replace(":m", f"'{month}'"), "project_changes": events_sql.replace(":m", f"'{month}'")}}


def _narrative(kpis: dict, events: list, clients: list, prev: str) -> dict:
    """Rules-based summary: every sentence is computed from the certified figures (no model-written text)."""
    pn = month_name(prev).split()[0]
    by = lambda t: [e for e in events if e["change_type"] == t]
    worse, better, downs = by("PERFORMANCE_WORSENED"), by("PERFORMANCE_IMPROVED"), by("RISK_DOWNGRADE")
    approved, signed, first = by("BOARD_APPROVED"), by("SIGNED"), by("FIRST_DISBURSEMENT")
    to_pd = [e for e in worse if e["to_value"] == "Past Due"]
    to_wl = [e for e in worse if e["to_value"] == "Watchlist"]
    det = [c for c in clients if c["direction"] == "Deteriorated"]
    k = lambda i: kpis.get(i) or {}

    def moved(kid, label, money=False):
        r = k(kid)
        a, b = r["previous_value"], r["value"]
        fmt = _money if money else (lambda v: f"{v:,.0f}")
        return f"{label} {'fell' if b < a else 'rose'} from {fmt(a)} to {fmt(b)}."

    right, wrong, steps = [], [], []
    if worse:
        wrong.append(f"{_plural(len(worse), 'project')} slipped in repayment status: {len(to_wl)} onto the Watchlist "
                     f"and {len(to_pd)} into Past Due ({_money(_amt(worse))} disbursed).")
    if better:
        right.append(f"{_plural(len(better), 'project')} recovered their repayment status ({_money(_amt(better))} disbursed).")
    for kid, label, money in [("M01", "Overdue monitoring reviews", False), ("R01", "Past Due projects", False),
                              ("R02", "Watchlist projects", False), ("R04", "Expected credit loss", True)]:
        if k(kid).get("previous_value") is None:
            continue
        if k(kid).get("assessment") == "Improving":
            right.append(moved(kid, label, money))
        elif k(kid).get("assessment") == "Deteriorating":
            wrong.append(moved(kid, label, money))
    if approved or signed or first:
        bits = [f"{len(approved)} Board approvals ({_money(_amt(approved))})" if approved else "",
                f"{len(signed)} signings" if signed else "", f"{len(first)} first disbursements" if first else ""]
        right.append("New business moved forward: " + ", ".join(b for b in bits if b) + ".")
    if downs:
        wrong.append(f"{_plural(len(downs), 'project')} had their internal risk rating downgraded.")
    if len(worse) >= 4:
        by_ind = {}
        for e in worse:
            by_ind[e["industry"]] = by_ind.get(e["industry"], 0) + 1
        ind, n = max(by_ind.items(), key=lambda x: x[1])
        if n / len(worse) >= 0.4:
            wrong.append(f"The slippage is concentrated in {ind}: {n} of the {len(worse)} projects.")

    if to_pd:
        names = sorted({e["client_name"] for e in to_pd}, key=lambda n: -_amt([e for e in to_pd if e["client_name"] == n]))
        steps.append(f"Refer the {_plural(len(names), 'client')} with a project newly in Past Due to the Credit Risk "
                     f"Committee, starting with {' and '.join(names[:2])}.")
    if to_wl:
        steps.append(f"Agree recovery plans for the {_plural(len(to_wl), 'project')} newly on the Watchlist before they "
                     "fall into Past Due.")
    if det:
        steps.append(f"Start with the largest deterioration: {det[0]['client_name']} ({_money(det[0]['exposure_musd'])} "
                     "of disbursed capital affected).")
    if k("M01").get("value"):
        steps.append(f"Clear the {k('M01')['value']:,.0f} overdue monitoring reviews, highest risk ratings first.")
    if not wrong:
        wrong.append(f"No material deterioration compared with {pn}.")
    if not right:
        right.append(f"No material improvement compared with {pn}.")
    if not steps:
        steps.append("No action needed beyond routine monitoring.")
    return {"went_right": right[:4], "went_wrong": wrong[:4], "next_steps": steps[:4]}


def _balance(events: list) -> dict:
    """The month's movements as worse-vs-better pairs (counts and amounts), computed from project_month_changes."""
    def side(types, pred=lambda e: True):
        rows = [e for e in events if e["change_type"] in types and pred(e)]
        return {"n": len(rows), "musd": round(_amt(rows), 2)}
    pairs = [
        {"id": "repayment", "label": "Repayment status", "worse_label": "slipped", "better_label": "recovered",
         "worse": side({"PERFORMANCE_WORSENED"}), "better": side({"PERFORMANCE_IMPROVED"}),
         "worse_filter": "attention", "better_filter": "improved"},
        {"id": "rating", "label": "Internal risk rating", "worse_label": "downgraded", "better_label": "upgraded",
         "worse": side({"RISK_DOWNGRADE"}), "better": side({"RISK_UPGRADE"}),
         "worse_filter": "attention", "better_filter": "improved"},
        {"id": "reviews", "label": "Monitoring reviews", "worse_label": "newly overdue", "better_label": "completed",
         "worse": side({"REVIEW_OVERDUE"}), "better": side({"REVIEW_OVERDUE_CLEARED"})},
        {"id": "data", "label": "Data-quality issues", "worse_label": "new", "better_label": "resolved",
         "worse": side({"DATA_ISSUE_NEW"}), "better": side({"DATA_ISSUE_RESOLVED"})},
    ]
    growth = {t: side({t}) for t in ("BOARD_APPROVED", "SIGNED", "FIRST_DISBURSEMENT", "NEW_PROJECT")}
    credit_bad = pairs[0]["worse"]["n"] + pairs[1]["worse"]["n"]
    credit_good = pairs[0]["better"]["n"] + pairs[1]["better"]["n"]
    verdict = ("improving" if credit_good > 1.5 * credit_bad else "deteriorating" if credit_bad > 1.5 * credit_good
               else "mixed")
    return {"pairs": pairs, "growth": growth, "verdict": verdict, "credit_better": credit_good, "credit_worse": credit_bad}


def _actions(kpis: dict, events: list, clients: list) -> list:
    """The month's follow-ups as structured actions: owner, amount at stake and the actual clients or projects."""
    by_client = {c["client_name"]: c for c in clients}
    worse = [e for e in events if e["change_type"] == "PERFORMANCE_WORSENED"]
    to_pd = [e for e in worse if e["to_value"] == "Past Due"]
    to_wl = [e for e in worse if e["to_value"] == "Watchlist"]
    downs = [e for e in events if e["change_type"] == "RISK_DOWNGRADE"]
    overdue_new = [e for e in events if e["change_type"] == "REVIEW_OVERDUE"]
    acts = []
    if to_pd:
        names = sorted({e["client_name"] for e in to_pd}, key=lambda n: -_amt([e for e in to_pd if e["client_name"] == n]))
        acts.append({"id": "refer_past_due", "priority": "high", "owner": "Credit Risk Committee",
                     "title": f"Refer {_plural(len(names), 'client')} with a project newly in Past Due",
                     "why": f"{_money(_amt(to_pd))} disbursed now in default (60% expected loss, A11)",
                     "items": [{"kind": "client", "name": n, "client_id": (by_client.get(n) or {}).get("client_id"),
                                "musd": round(_amt([e for e in to_pd if e["client_name"] == n]), 2),
                                "detail": ", ".join(sorted({e["project_name"] for e in to_pd if e["client_name"] == n}))}
                               for n in names],
                     "cta": "send"})
    if to_wl:
        acts.append({"id": "watchlist_plans", "priority": "medium", "owner": "Portfolio monitoring team",
                     "title": f"Agree recovery plans for {_plural(len(to_wl), 'project')} newly on the Watchlist",
                     "why": f"{_money(_amt(to_wl))} disbursed; act before they fall into Past Due",
                     "items": [{"kind": "client", "name": e["client_name"], "client_id": (by_client.get(e["client_name"]) or {}).get("client_id"),
                                "musd": round(float(e.get("amount_musd") or 0), 2), "detail": e["project_name"]}
                               for e in sorted(to_wl, key=lambda e: -float(e.get("amount_musd") or 0))],
                     "cta": "send"})
    if downs:
        acts.append({"id": "rating_downgrades", "priority": "medium", "owner": "Investment department",
                     "title": f"Confirm the {_plural(len(downs), 'risk-rating downgrade')}",
                     "why": f"{_money(_amt(downs))} disbursed on projects whose rating worsened",
                     "items": [{"kind": "client", "name": e["client_name"], "client_id": (by_client.get(e["client_name"]) or {}).get("client_id"),
                                "musd": round(float(e.get("amount_musd") or 0), 2),
                                "detail": f"{e['project_name']}: {e['from_value']} → {e['to_value']}"}
                               for e in sorted(downs, key=lambda e: -float(e.get("amount_musd") or 0))],
                     "cta": "send"})
    total_overdue = (kpis.get("M01") or {}).get("value")
    if total_overdue:
        acts.append({"id": "overdue_reviews", "priority": "routine", "owner": "Portfolio monitoring team",
                     "title": f"Clear {int(total_overdue):,} overdue monitoring reviews, highest risk ratings first",
                     "why": f"{len(overdue_new)} became overdue this month",
                     "items": [], "cta": "early_warning"})
    return acts


def client_month(client_name: str, month: str) -> dict:
    hist_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, count(*) AS projects,
       count_if(status = 'Active') AS active, count_if(performance_status = 'Past Due') AS past_due,
       count_if(performance_status = 'Watchlist') AS watchlist,
       round(sum(coalesce(current_disbursed_exposure_musd, 0)), 2) AS exposure_musd,
       round(sum(coalesce(expected_credit_loss_musd, 0)), 2) AS ecl_musd,
       round(avg(CASE WHEN status = 'Active' THEN internal_risk_rating END), 2) AS avg_rating,
       count_if(mon_flag_review_overdue) AS reviews_overdue
FROM {M(HIST)}
WHERE client_name = :c
GROUP BY 1 ORDER BY 1"""
    ev_sql = f"""SELECT project_name, change_type, impact, from_value, to_value, amount_musd
FROM {M('project_month_changes')}
WHERE client_name = :c AND date_format(reporting_month, 'yyyy-MM') = :m
  AND change_type NOT IN ('DATA_ISSUE_NEW', 'DATA_ISSUE_RESOLVED')
ORDER BY CASE impact WHEN 'Negative' THEN 1 WHEN 'Positive' THEN 2 ELSE 3 END, abs(amount_musd) DESC NULLS LAST"""
    hist = q(hist_sql, {"c": client_name})
    for h in hist:
        h["month_name"] = month_name(h["month"])
    events = [{**e, "text": describe(e)} for e in q(ev_sql, {"c": client_name, "m": month})]
    lit = "'" + client_name.replace("'", "''") + "'"
    return {"client_name": client_name, "history": hist, "events": events,
            "evidence": {"client_history": hist_sql.replace(":c", lit),
                         "client_changes": ev_sql.replace(":c", lit).replace(":m", f"'{month}'")}}
