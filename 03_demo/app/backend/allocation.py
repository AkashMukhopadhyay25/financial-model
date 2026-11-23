"""
Capital allocation engine: deterministic SQL on the certified tables plus curated, cited market outlooks.

The Capital Allocation Agent (allocation_agent.py) only chooses which views to pull and explains them; every figure
comes from these queries, and every market claim comes from ref_market_outlook (A24: curated, dated, cited sources;
no live web).

Method (A23, thresholds in business.capital_allocation):
  * Segments: industry, region or industry x region, with at least min_active_projects Active projects.
  * Four credit metrics from our own data, each ranked across segments (1 = best), overall = average rank:
      distressed share  = Past Due + Watchlist disbursed / current exposure (A09)
      ECL rate          = expected credit loss (A11) / current exposure
      closed loss rate  = disbursed on projects exited at a loss / disbursed on all closed projects (track record)
      weighted rating   = exposure-weighted internal risk rating (1 best .. 6 worst)
  * Concentration: a segment holding more than max_segment_share of current exposure is flagged.
  * External outlooks are shown beside the ranking, never blended into it.
"""
from pathlib import Path

from .queries import T, q, render
from .settings import REPO_CONFIG, get_settings
from .stress import INDUSTRIES, REGIONS, run_scenario

DIMENSIONS = {"industry": ["industry"], "region": ["region"], "industry_region": ["industry", "region"]}


def _params():
    s = get_settings()
    return {"min_active": s.alloc_min_active_projects, "max_share": s.alloc_max_segment_share}


def rank_segments(dimension="industry", industry="", region="") -> dict:
    if dimension not in DIMENSIONS:
        return {"error": f"dimension must be one of {list(DIMENSIONS)}"}
    if industry and industry not in INDUSTRIES:
        return {"error": f"unknown industry {industry!r}; use one of {INDUSTRIES}"}
    if region and region not in REGIONS:
        return {"error": f"unknown region {region!r}; use one of {REGIONS}"}
    cols = DIMENSIONS[dimension]
    keys = ", ".join(cols)
    p = _params()
    params = {"min_active": p["min_active"], "max_share": p["max_share"], "industry": industry, "region": region}
    sql = f"""WITH seg AS (
  SELECT {keys},
         count_if(status = 'Active') AS active_projects,
         count(DISTINCT CASE WHEN status = 'Active' THEN client_id END) AS active_clients,
         round(sum(coalesce(current_disbursed_exposure_musd, 0)), 2) AS current_exposure_musd,
         round(sum(CASE WHEN performance_status IN ('Past Due', 'Watchlist') THEN current_disbursed_exposure_musd ELSE 0 END)
               / nullif(sum(current_disbursed_exposure_musd), 0), 4) AS distressed_share,
         round(sum(coalesce(expected_credit_loss_musd, 0)) / nullif(sum(current_disbursed_exposure_musd), 0), 4) AS ecl_rate,
         round(sum(CASE WHEN status = 'Closed' AND performance_status = 'Exited at a loss' THEN disbursed_musd ELSE 0 END)
               / nullif(sum(CASE WHEN status = 'Closed' THEN disbursed_musd ELSE 0 END), 0), 4) AS closed_loss_rate,
         round(sum(current_disbursed_exposure_musd * internal_risk_rating) / nullif(sum(current_disbursed_exposure_musd), 0), 2)
           AS weighted_risk_rating,
         round(sum(coalesce(undisbursed_commitment_musd, 0)), 2) AS undisbursed_musd,
         round(sum(coalesce(pipeline_unsigned_musd, 0)), 2) AS pipeline_unsigned_musd,
         round(sum(coalesce(expected_credit_loss_musd, 0)), 2) AS ecl_musd
  FROM {T('certified_investment_portfolio')}
  WHERE (:industry = '' OR industry = :industry) AND (:region = '' OR region = :region)
  GROUP BY {keys}
), ranked AS (
  SELECT *,
         round(current_exposure_musd / sum(current_exposure_musd) OVER (), 4) AS portfolio_share,
         rank() OVER (ORDER BY distressed_share)    AS rank_distressed,
         rank() OVER (ORDER BY ecl_rate)            AS rank_ecl,
         rank() OVER (ORDER BY closed_loss_rate)    AS rank_closed_loss,
         rank() OVER (ORDER BY weighted_risk_rating) AS rank_rating
  FROM seg WHERE active_projects >= CAST(:min_active AS INT)
)
SELECT *,
       round((rank_distressed + rank_ecl + rank_closed_loss + rank_rating) / 4.0, 2) AS average_rank,
       rank() OVER (ORDER BY (rank_distressed + rank_ecl + rank_closed_loss + rank_rating)) AS overall_rank,
       portfolio_share > CAST(:max_share AS DOUBLE) AS concentration_flag
FROM ranked
ORDER BY overall_rank, current_exposure_musd DESC
LIMIT 20"""
    rows = q(sql, params)
    return {"dimension": dimension, "rows": rows, "segments_ranked": len(rows),
            "method": (f"Segments with {p['min_active']}+ Active projects, ranked on four credit metrics from certified "
                       "data (1 = best): distressed share of exposure, ECL rate, closed-project loss rate, exposure-weighted "
                       "risk rating; overall = average rank. Concentration flag above "
                       f"{p['max_share']:.0%} of current exposure. Shares are fractions (0.201 = 20.1%)."),
            "assumption_ids": ["A09", "A11", "A23"], "sql": render(sql, params)}


def _outlook_rows():
    try:
        return q(f"""SELECT source_id, publisher, title, CAST(published_date AS STRING) AS published_date, url, industry,
                            region, stance, finding, CAST(retrieved_date AS STRING) AS retrieved_date
                     FROM {T('ref_market_outlook')} ORDER BY source_id"""), f"SELECT * FROM {T('ref_market_outlook')}"
    except Exception:  # local development before 00_reference has run: read the same curated file
        import yaml

        path = Path(REPO_CONFIG).parent / "market_outlook.yml"
        d = yaml.safe_load(path.read_text())
        rows = [{**{k: str(v) for k, v in s.items()}, "retrieved_date": str(d.get("retrieved_date"))} for s in d["sources"]]
        return rows, f"-- read from {path.name} (ref_market_outlook not found)"


def market_outlook(industry="", region="") -> dict:
    rows, sql = _outlook_rows()
    ind, reg = (industry or "").strip(), (region or "").strip()
    keep = [r for r in rows if (not ind or r["industry"] in ("ALL", ind)) and (not reg or r["region"] in ("ALL", reg))]
    return {"rows": keep, "assumption_ids": ["A24"], "sql": sql,
            "note": "Curated external research (A24): paraphrased from the publisher's summary, cited and dated. "
                    "Cite as [S#] with publisher and date."}


def clients_in_segment(industry="", region="", band="", limit=8) -> dict:
    if band and band not in ("CONTINUE", "MONITOR", "REDUCE_OR_REVIEW"):
        return {"error": "band must be CONTINUE, MONITOR, REDUCE_OR_REVIEW or empty"}
    params = {"industry": industry or "", "region": region or "", "band": band or ""}
    sql = f"""SELECT client_id, client_name, primary_industry, primary_region, band, health_score,
       n_active, n_past_due, n_watchlist,
       round(current_disbursed_exposure_musd, 2) AS current_exposure_musd,
       round(undisbursed_commitment_musd, 2) AS undisbursed_musd,
       round(pipeline_unsigned_musd, 2) AS pipeline_unsigned_musd,
       round(exposure_affected_musd, 2) AS exposure_affected_musd, band_evidence
FROM {T('certified_client_scorecard')}
WHERE (:industry = '' OR primary_industry = :industry) AND (:region = '' OR primary_region = :region)
  AND (:band = '' OR band = :band)
ORDER BY exposure_affected_musd DESC
LIMIT {max(1, min(int(limit or 8), 15))}"""
    return {"rows": q(sql, params), "assumption_ids": ["A15"], "sql": render(sql, params)}


def board_recommendations() -> dict:
    """The WS3 four clients, each with its segment's A23 ranks, concentration flag and A24 market stance attached
    (joined here, deterministically, so the agent never has to look them up or infer them)."""
    sql = f"""SELECT r.recommendation, r.client_id, r.client_name, r.primary_industry, r.primary_region,
       round(r.exposure_affected_musd, 2) AS exposure_affected_musd,
       round(r.current_disbursed_exposure_musd, 2) AS current_exposure_musd,
       round(r.undisbursed_commitment_musd, 2) AS undisbursed_musd, r.evidence_summary
FROM {T('ws3_recommendations')} r ORDER BY r.recommendation, r.exposure_affected_musd DESC"""
    rows = q(sql)
    ind = {r["industry"]: r for r in rank_segments("industry")["rows"]}
    reg = {r["region"]: r for r in rank_segments("region")["rows"]}
    both = {(r["industry"], r["region"]): r for r in rank_segments("industry_region")["rows"]}
    outlook = market_outlook()["rows"]
    n_ind, n_reg = len(ind), len(reg)
    for r in rows:
        i, g = ind.get(r["primary_industry"], {}), reg.get(r["primary_region"], {})
        ir = both.get((r["primary_industry"], r["primary_region"]))
        r["industry_rank"] = f"{i.get('overall_rank', '-')} of {n_ind}"
        r["region_rank"] = f"{g.get('overall_rank', '-')} of {n_reg}"
        r["region_portfolio_share"] = g.get("portfolio_share")
        r["region_concentration_flag"] = bool(g.get("concentration_flag"))
        r["industry_x_region_rank"] = f"{ir['overall_rank']} of {len(both)}" if ir else "not ranked (fewer Active projects)"
        r["market_stance_industry"] = [f"{o['source_id']} {o['stance']}" for o in outlook if o["industry"] == r["primary_industry"]]
        r["market_stance_region"] = [f"{o['source_id']} {o['stance']}" for o in outlook if o["region"] == r["primary_region"]]
    concentrated = sorted({r["primary_region"] for r in rows if r["region_concentration_flag"]})
    return {"rows": rows, "sql": sql,
            "regions_over_concentration_limit": concentrated,
            "note": "The four-client recommendation from the WS3 notebook (rule-based bands A15, ranked by exposure), with "
                    "each client's industry and region rank (A23, 1 = best), concentration flag and market stances (A24)."}


def segment_downside(industry="", region="") -> dict:
    """What a prioritised or cautioned segment would cost if its Watchlist projects defaulted (A11 loss rate)."""
    r = run_scenario(migrate_watchlist=True, industry=industry, region=region, group_by="client",
                     name=f"Watchlist defaults in {industry or 'all industries'} / {region or 'all regions'}")
    if r.get("error"):
        return r
    s = r["summary"]
    return {"scenario": r["name"],
            "summary": {k: s[k] for k in ("ecl_baseline_musd", "ecl_stressed_musd", "ecl_increase_musd",
                                          "shocked_projects", "shocked_clients", "shocked_exposure_musd",
                                          "shocked_undisbursed_musd", "shocked_projects_with_dq_issues",
                                          "shocked_projects_high_severity")},
            "top_clients": r["breakdown"][:5], "assumptions": r["assumptions"], "assumption_ids": r["assumption_ids"],
            "sql": r["sql"]}


def allocation_summary() -> dict:
    """The A23 decision rule, applied deterministically: the agent explains this view, it does not choose it.
      prioritise industry = overall rank 1; caution industry = last rank;
      regions to grow     = the two best-ranked regions that are not concentration-flagged;
      regions to limit    = concentration-flagged regions plus the bottom-ranked region;
      best segments       = top industry x region segments outside the regions to limit."""
    ind = rank_segments("industry")["rows"]
    reg = rank_segments("region")["rows"]
    seg = rank_segments("industry_region")["rows"]
    outlook = market_outlook()["rows"]
    ind_sorted = sorted(ind, key=lambda r: r["overall_rank"])
    reg_sorted = sorted(reg, key=lambda r: r["overall_rank"])
    limit = [r["region"] for r in reg_sorted if r["concentration_flag"]]
    if reg_sorted and reg_sorted[-1]["region"] not in limit:
        limit.append(reg_sorted[-1]["region"])
    grow = [r["region"] for r in reg_sorted if r["region"] not in limit][:2]
    best = [f"{r['industry']} in {r['region']} (rank {r['overall_rank']} of {len(seg)})"
            for r in sorted(seg, key=lambda r: r["overall_rank"]) if r["region"] not in limit][:3]

    def stance(industry):
        return [f"[{o['source_id']}] {o['publisher']}, {o['published_date']}: {o['stance']}" for o in outlook
                if o["industry"] == industry]

    top, bottom = ind_sorted[0], ind_sorted[-1]
    return {
        "prioritise_industry": top["industry"], "prioritise_industry_rank": f"1 of {len(ind)}",
        "caution_industry": bottom["industry"], "caution_industry_rank": f"{bottom['overall_rank']} of {len(ind)}",
        "regions_to_grow": grow, "regions_to_limit": limit,
        "concentration_limit": get_settings().alloc_max_segment_share,
        "best_segments_outside_limited_regions": best,
        "market_view_prioritise_industry": stance(top["industry"]),
        "market_view_caution_industry": stance(bottom["industry"]),
        "data_and_market_agree": {
            top["industry"]: any("prioritise" in s for s in stance(top["industry"])),
            bottom["industry"]: any("caution" in s for s in stance(bottom["industry"]))},
        "rule": "A23: prioritise the best-ranked industry, caution on the last; grow in the best-ranked regions that are not "
                "concentration-flagged; limit flagged and bottom-ranked regions. Market outlooks (A24) are compared, "
                "not blended.",
        "assumption_ids": ["A23", "A24"],
    }
