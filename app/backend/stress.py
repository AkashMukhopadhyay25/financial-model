"""
Reserve & stress-test engine: deterministic SQL on certified_investment_portfolio.

The Stress-Test Agent (stress_agent.py) only chooses the scenario parameters; every figure comes from these queries,
so the same scenario always returns the same numbers, however the question was phrased.

Scenario model (stated assumptions, shown with every result):
  * Scope: Active projects (current exposure, A09). Closed, Dropped and Pending projects carry no credit exposure here.
  * Baseline expected credit loss (A11): Past Due projects are in default; loss = loss rate (A11, 60%) x disbursed.
  * Shock: Active projects that are not yet Past Due move to default when they match the scenario
    (Watchlist migration and/or internal risk rating >= a threshold), within the optional filters
    (region, country, industry, client, environmental category).
  * Stressed ECL = scenario loss rate x (disbursed + drawdown share x undisbursed commitment) over every defaulted
    project: the existing Past Due projects (portfolio-wide) plus the shocked ones.
    Drawdown share = part of the undisbursed commitment (A10) assumed drawn before default; 0 by default (A11 as is).
  * A scenario is a what-if, not a forecast.
"""
from .queries import T, q, render
from .settings import get_settings

REGIONS = ["East Asia & Pacific", "Europe & Central Asia", "Latin America", "Middle East", "North America",
           "South Asia", "Sub-Saharan Africa"]
INDUSTRIES = ["Agribusiness", "Energy", "Finance", "Manufacturing", "Telecom"]
GROUP_COLUMNS = {"region": "region", "country": "country", "industry": "industry", "client": "client_name",
                 "risk_rating": "CAST(internal_risk_rating AS STRING)",
                 "environmental_category": "environmental_category"}


NORTH_AFRICA = ["Egypt", "Morocco", "Tunisia", "Algeria", "Libya"]


def _countries(country) -> str:
    """Country filter as a '|'-separated lower-case list ('' = all). Accepts a name, a list, or 'North Africa'."""
    if isinstance(country, (list, tuple)):
        names = [str(c) for c in country]
    else:
        names = [c for c in str(country or "").replace(";", ",").split(",")]
    out = []
    for n in (n.strip() for n in names):
        if not n:
            continue
        out += NORTH_AFRICA if n.lower() == "north africa" else [n]
    return "|".join(dict.fromkeys(n.lower() for n in out))


def _filters(region="", country="", industry="", client="", environmental_category="") -> dict:
    return {"region": (region or "").strip(), "country": _countries(country),
            "industry": (industry or "").strip(), "client": (client or "").strip(),
            "env_cat": (environmental_category or "").strip().upper()[:1]}


FILTER_SQL = """(:region = '' OR region = :region)
      AND (:country = '' OR concat('|', :country, '|') LIKE concat('%|', lower(country), '|%'))
      AND (:industry = '' OR industry = :industry)
      AND (:client = '' OR client_id = :client OR lower(client_name) LIKE concat('%', lower(:client), '%'))
      AND (:env_cat = '' OR environmental_category = :env_cat)"""


def _scenario_cte() -> str:
    return f"""WITH base AS (
  SELECT project_url, project_number, project_name, client_id, client_name, region, country, industry,
         environmental_category, internal_risk_rating, performance_status,
         coalesce(current_disbursed_exposure_musd, 0) AS exposure_musd,
         coalesce(undisbursed_commitment_musd, 0)     AS undisbursed_musd,
         coalesce(expected_credit_loss_musd, 0)       AS ecl_baseline_musd,
         coalesce(needs_review, false) AS needs_review, dq_max_severity,
         performance_status = 'Past Due' AS is_past_due,
         (performance_status <> 'Past Due'
          AND {FILTER_SQL}
          AND ((CAST(:migrate_watchlist AS INT) = 1 AND performance_status = 'Watchlist')
               OR (CAST(:min_rating AS INT) > 0 AND internal_risk_rating >= CAST(:min_rating AS INT)))) AS is_shocked
  FROM {T('certified_investment_portfolio')}
  WHERE status = 'Active'
), s AS (
  SELECT *,
         CASE WHEN is_past_due OR is_shocked
              THEN CAST(:loss_rate AS DOUBLE) * (exposure_musd + CAST(:drawdown_share AS DOUBLE) * undisbursed_musd)
              ELSE 0 END AS ecl_stressed_musd
  FROM base
)"""


def run_scenario(migrate_watchlist=False, min_rating=0, loss_rate=None, drawdown_share=0.0, group_by="region",
                 region="", country="", industry="", client="", environmental_category="", name="") -> dict:
    a11 = get_settings().ecl_loss_rate
    loss_rate = a11 if loss_rate in (None, "") else float(loss_rate)
    min_rating = int(min_rating or 0)
    drawdown_share = float(drawdown_share or 0)
    errors = []
    if not 0 < loss_rate <= 1:
        errors.append("loss_rate must be between 0 and 1")
    if not 0 <= drawdown_share <= 1:
        errors.append("drawdown_share must be between 0 and 1")
    if not 0 <= min_rating <= 6:
        errors.append("min_rating must be 0 (off) or 1-6")
    if region and region not in REGIONS:
        errors.append(f"unknown region {region!r}; use one of {REGIONS} (North Africa is in 'Middle East': filter by country)")
    if industry and industry not in INDUSTRIES:
        errors.append(f"unknown industry {industry!r}; use one of {INDUSTRIES}")
    if group_by not in GROUP_COLUMNS:
        errors.append(f"group_by must be one of {list(GROUP_COLUMNS)}")
    if errors:
        return {"error": "; ".join(errors)}

    params = {"migrate_watchlist": 1 if migrate_watchlist else 0, "min_rating": min_rating, "loss_rate": loss_rate,
              "drawdown_share": drawdown_share,
              **_filters(region, country, industry, client, environmental_category)}
    cte = _scenario_cte()
    summary_sql = f"""{cte}
SELECT count(*) AS active_projects,
       round(sum(exposure_musd), 2) AS active_exposure_musd,
       count_if(is_past_due) AS past_due_projects,
       round(sum(ecl_baseline_musd), 2) AS ecl_baseline_musd,
       count_if(is_shocked) AS shocked_projects,
       count_if(is_shocked AND performance_status = 'Watchlist') AS shocked_watchlist_projects,
       count_if(is_shocked AND performance_status = 'Performing') AS shocked_performing_projects,
       count(DISTINCT CASE WHEN is_shocked THEN client_id END) AS shocked_clients,
       round(sum(CASE WHEN is_shocked THEN exposure_musd ELSE 0 END), 2) AS shocked_exposure_musd,
       round(sum(CASE WHEN is_shocked THEN undisbursed_musd ELSE 0 END), 2) AS shocked_undisbursed_musd,
       round(sum(ecl_stressed_musd), 2) AS ecl_stressed_musd,
       round(sum(ecl_stressed_musd) - sum(ecl_baseline_musd), 2) AS ecl_increase_musd,
       round(sum(CASE WHEN is_shocked THEN ecl_stressed_musd ELSE 0 END), 2) AS ecl_increase_from_shocked_projects_musd,
       round(sum(CASE WHEN is_past_due THEN ecl_stressed_musd - ecl_baseline_musd ELSE 0 END), 2)
         AS ecl_increase_from_existing_past_due_musd,
       count_if(is_shocked AND needs_review) AS shocked_projects_with_dq_issues,
       count_if(is_shocked AND dq_max_severity = 'high') AS shocked_projects_high_severity
FROM s"""
    gcol = GROUP_COLUMNS[group_by]
    breakdown_sql = f"""{cte}
SELECT {gcol} AS {group_by},
       count_if(is_shocked) AS shocked_projects,
       round(sum(CASE WHEN is_shocked THEN exposure_musd ELSE 0 END), 2) AS shocked_exposure_musd,
       round(sum(ecl_baseline_musd), 2) AS ecl_baseline_musd,
       round(sum(ecl_stressed_musd), 2) AS ecl_stressed_musd,
       round(sum(ecl_stressed_musd) - sum(ecl_baseline_musd), 2) AS ecl_increase_musd
FROM s
GROUP BY {gcol}
HAVING count_if(is_shocked) > 0
ORDER BY ecl_increase_musd DESC
LIMIT 10"""
    projects_sql = f"""{cte}
SELECT project_url, project_number, project_name, client_name, country, industry, performance_status, internal_risk_rating,
       round(exposure_musd, 2) AS exposure_musd, round(undisbursed_musd, 2) AS undisbursed_musd,
       round(ecl_stressed_musd, 2) AS ecl_stressed_musd, needs_review
FROM s WHERE is_shocked
ORDER BY ecl_stressed_musd DESC
LIMIT 10"""
    summary = q(summary_sql, params)[0]
    summary = {k: (0 if v is None else v) for k, v in summary.items()}
    breakdown = q(breakdown_sql, params)
    projects = q(projects_sql, params)

    shock = []
    if migrate_watchlist:
        shock.append("Watchlist projects move to default")
    if min_rating:
        shock.append(f"Active projects rated {min_rating} or worse move to default")
    scope = [f"{k}={v}" for k, v in (("region", region), ("country", params["country"].replace("|", ", ")), ("industry", industry),
                                     ("client", client), ("environmental category", environmental_category)) if v]
    assumptions = [
        "Scope: Active projects (current exposure, A09).",
        "Baseline: Past Due projects are in default; ECL = 60% of disbursed (A11).",
        "Stressed ECL is portfolio-wide: existing Past Due projects everywhere plus the shocked projects. The increase "
        "is split into newly defaulted projects and the change on existing Past Due projects (loss rate or drawdown).",
        ("Shock: " + "; ".join(shock) + (f" (within {', '.join(scope)})" if scope else " (whole portfolio)") + ".")
        if shock else "No migration: existing Past Due projects only.",
        f"Loss rate {loss_rate:.0%}" + (" (A11)." if abs(loss_rate - a11) < 1e-9 else f" (A11 uses {a11:.0%}; scenario override)."),
        f"Drawdown: {drawdown_share:.0%} of the undisbursed commitment of defaulted projects assumed drawn before default"
        + (" (A11 as is)." if not drawdown_share else " (scenario assumption)."),
        "A what-if, not a forecast. Projects with open data-quality issues are included, not excluded.",
    ]
    return {
        "name": name or ("; ".join(shock) or "Baseline"),
        "parameters": {"migrate_watchlist": bool(migrate_watchlist), "min_rating": min_rating, "loss_rate": loss_rate,
                       "drawdown_share": drawdown_share, "group_by": group_by, "region": region, "country": country,
                       "industry": industry, "client": client, "environmental_category": environmental_category},
        "summary": summary,
        "breakdown": breakdown,
        "top_projects": projects,
        "assumptions": assumptions,
        "assumption_ids": ["A09", "A10", "A11"],
        "sql": render(summary_sql, params),
        "sql_breakdown": render(breakdown_sql, params),
    }


def risk_baseline(group_by="region", region="", country="", industry="", client="", environmental_category="") -> dict:
    if group_by not in GROUP_COLUMNS:
        return {"error": f"group_by must be one of {list(GROUP_COLUMNS)}"}
    params = _filters(region, country, industry, client, environmental_category)
    gcol = GROUP_COLUMNS[group_by]
    sql = f"""SELECT {gcol} AS {group_by},
       count(*) AS active_projects,
       count_if(performance_status = 'Past Due') AS past_due_projects,
       count_if(performance_status = 'Watchlist') AS watchlist_projects,
       count_if(internal_risk_rating >= 5) AS projects_rated_5_6,
       round(sum(coalesce(current_disbursed_exposure_musd, 0)), 2) AS current_exposure_musd,
       round(sum(CASE WHEN performance_status = 'Watchlist' THEN current_disbursed_exposure_musd ELSE 0 END), 2) AS watchlist_exposure_musd,
       round(sum(coalesce(undisbursed_commitment_musd, 0)), 2) AS undisbursed_musd,
       round(sum(coalesce(expected_credit_loss_musd, 0)), 2) AS ecl_baseline_musd
FROM {T('certified_investment_portfolio')}
WHERE status = 'Active' AND {FILTER_SQL}
GROUP BY {gcol}
ORDER BY current_exposure_musd DESC
LIMIT 15"""
    rows = q(sql, params)
    return {"group_by": group_by, "rows": rows, "sql": render(sql, params), "assumption_ids": ["A09", "A10", "A11"]}


def assumptions(ids=None) -> dict:
    ids = [i.strip().upper() for i in (ids or ["A09", "A10", "A11"]) if i and i.strip()][:10]
    marks = ", ".join(f":a{i}" for i in range(len(ids)))
    sql = f"SELECT assumption_id, topic, statement FROM {T('ref_assumptions')} WHERE assumption_id IN ({marks}) ORDER BY assumption_id"
    params = {f"a{i}": v for i, v in enumerate(ids)}
    return {"rows": q(sql, params), "sql": render(sql, params)}
