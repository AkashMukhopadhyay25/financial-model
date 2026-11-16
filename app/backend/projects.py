"""
Project-level views and the portfolio's strengths, all from certified_investment_portfolio.

  strengths()          what is going well: performing share, completed track record, climate, renewables, MSME, reach,
                       approval momentum (balances the risk views with facts of the same rigour)
  spotlight(view)      project lists for the Overview: largest Active, recently approved, needs attention
  detail(project_url)  one project: lifecycle, monitoring, amounts, text-derived attributes, data-quality flags in words
"""
from .queries import T, q, render

STRENGTHS_SQL = """SELECT
  count_if(status = 'Active') AS active_projects,
  count_if(status = 'Active' AND performance_status = 'Performing') AS performing_projects,
  round(sum(CASE WHEN status = 'Active' AND performance_status = 'Performing' THEN current_disbursed_exposure_musd ELSE 0 END)
        / nullif(sum(current_disbursed_exposure_musd), 0), 4) AS performing_exposure_share,
  count_if(status = 'Closed') AS closed_projects,
  count_if(status = 'Closed' AND performance_status = 'Completed') AS completed_projects,
  round(sum(CASE WHEN status = 'Closed' AND performance_status = 'Completed' THEN disbursed_musd ELSE 0 END)
        / nullif(sum(CASE WHEN status = 'Closed' THEN disbursed_musd ELSE 0 END), 0), 4) AS completed_disbursed_share,
  count_if(is_climate_related) AS climate_projects,
  round(sum(CASE WHEN is_climate_related THEN total_approved_musd ELSE 0 END), 2) AS climate_approved_musd,
  count_if(is_new_renewable_generation) AS renewable_projects,
  round(sum(CASE WHEN is_new_renewable_generation THEN new_capacity_mw ELSE 0 END), 0) AS renewable_capacity_mw,
  count_if(is_msme_financing) AS msme_projects,
  count(DISTINCT country) AS countries,
  count_if(status = 'Active' AND internal_risk_rating <= 2) AS active_rated_1_2
FROM {P}"""

MOMENTUM_SQL = """SELECT approval_fy, count(*) AS projects, round(sum(total_approved_musd), 2) AS approved_musd
FROM {P} WHERE approval_fy IS NOT NULL GROUP BY approval_fy ORDER BY approval_fy"""


def strengths() -> dict:
    P = T("certified_investment_portfolio")
    s = q(STRENGTHS_SQL.format(P=P))[0]
    years = q(MOMENTUM_SQL.format(P=P))
    best = max(years, key=lambda r: r["approved_musd"]) if years else None
    latest = years[-1] if years else None
    prev = years[-2] if len(years) > 1 else None
    return {**s, "approvals_by_fy": years, "record_fy": best, "latest_fy": latest, "previous_fy": prev,
            "sql": {"strengths": STRENGTHS_SQL.format(P=P), "approvals_by_fy": MOMENTUM_SQL.format(P=P)},
            "assumption_ids": ["A01", "A09", "A12", "A13", "A14"]}


SPOT_COLUMNS = """project_url, project_number, project_name, client_name, client_id, country, region, industry, status,
       performance_status, internal_risk_rating, environmental_category, approval_date,
       round(total_approved_musd, 2) AS approved_musd, round(disbursed_musd, 2) AS disbursed_musd,
       round(current_disbursed_exposure_musd, 2) AS current_exposure_musd, risk_flag, needs_review,
       dq_max_severity, dq_flag_ids, dq_messages, is_climate_related, is_new_renewable_generation"""

SPOTLIGHT = {
    "largest": ("Largest Active projects by current exposure (A09)",
                "status = 'Active'", "current_disbursed_exposure_musd DESC"),
    "recent": ("Most recently approved projects",
               "approval_date IS NOT NULL AND status <> 'Dropped'", "approval_date DESC, total_approved_musd DESC"),
    "performing": ("Largest Active projects that are performing with a low risk rating (1-3)",
                   "status = 'Active' AND performance_status = 'Performing' AND internal_risk_rating <= 3",
                   "current_disbursed_exposure_musd DESC"),
    # Same definition as "Projects to review" on Early warning (queries.early_warning): clients with A22 signals.
    "attention": ("Projects to review (same as Early warning): Active projects of flagged clients that are Past Due or "
                  "Watchlist, rated 5-6, or overdue for review (A18, A22)",
                  "status = 'Active' AND (performance_status IN ('Past Due', 'Watchlist') OR internal_risk_rating >= 5 "
                  "OR mon_flag_review_overdue) AND client_id IN (SELECT client_id FROM {EW})",
                  "CASE performance_status WHEN 'Past Due' THEN 1 WHEN 'Watchlist' THEN 2 ELSE 3 END, "
                  "current_disbursed_exposure_musd DESC"),
}


def spotlight(view: str = "largest", limit: int = 10) -> dict:
    if view not in SPOTLIGHT:
        view = "largest"
    title, where, order = SPOTLIGHT[view]
    where = where.format(EW=T("certified_early_warning"))
    P = T("certified_investment_portfolio")
    sql = f"SELECT {SPOT_COLUMNS}\nFROM {P}\nWHERE {where}\nORDER BY {order}\nLIMIT {max(1, min(int(limit), 50))}"
    count_sql = f"SELECT count(*) AS n FROM {P} WHERE {where}"
    return {"view": view, "title": title, "rows": q(sql), "total": int(q(count_sql)[0]["n"]), "sql": sql}


def detail(project_url: str) -> dict:
    P = T("certified_investment_portfolio")
    sql = f"""SELECT project_url, project_number, project_name, client_id, client_name, country, region, region_as_reported,
       industry, department, product_line, environmental_category, document_type, status, performance_status,
       internal_risk_rating, risk_flag, currency, climate_flag, is_climate_related,
       date_disclosed, projected_board_date, approval_date, signed_date, invested_date, as_of_date, reporting_date,
       days_since_last_review, days_approval_to_signing, days_signing_to_investment,
       amt_loan_musd, amt_equity_musd, amt_guarantee_musd, amt_risk_mgmt_musd, total_approved_musd, alloc_gap_musd,
       disbursed_musd, current_disbursed_exposure_musd, undisbursed_commitment_musd, pipeline_unsigned_musd,
       expected_credit_loss_musd, is_new_renewable_generation, new_capacity_mw, is_msme_financing, msme_target_group,
       described_product, text_attributes_need_review, text_review_reason, project_description,
       needs_review, dq_max_severity, review_owners, dq_messages, dq_flag_ids, dq_flag_count
FROM {P} WHERE project_url = :url"""
    rows = q(sql, {"url": project_url})
    if not rows:
        return {}
    r = rows[0]
    msgs = [m.strip() for m in (r.get("dq_messages") or "").split("|") if m.strip()]
    ids = [i.strip() for i in (r.get("dq_flag_ids") or "").split(",") if i.strip()]
    r["dq_flags"] = [{"id": ids[i] if i < len(ids) else "", "message": m} for i, m in enumerate(msgs)]
    others = q(f"""SELECT project_url, project_name, status, performance_status, round(total_approved_musd, 2) AS approved_musd
FROM {P} WHERE client_id = :cid AND project_url <> :url ORDER BY approval_date DESC LIMIT 8""",
               {"cid": r.get("client_id") or "", "url": project_url}) if r.get("client_id") else []
    return {"project": r, "client_projects": others, "sql": render(sql, {"url": project_url})}
