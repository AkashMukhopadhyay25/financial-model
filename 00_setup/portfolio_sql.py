"""
SQL for the client-level views built on certified_investment_portfolio:

  certified_client_scorecard   one row per monitored client: exposure, credit risk, performance, band (A15)
  certified_early_warning      one row per client with at least one emerging-risk signal (A22)

A plain Python file (not a notebook) so the same SQL is used by `01_data/07_client_views` on Databricks and by the
app's local preview (DuckDB). Keep the SQL to functions both engines share: count_if, mode, nullif, greatest,
concat_ws, round, rank() OVER, CAST(... AS STRING).

Every threshold comes from 00_setup/config/pipeline_config.yml (`business.client_bands`, `business.health_score_weights`,
`business.early_warning`); nothing is hard-coded here.
"""


def client_scorecard_sql(portfolio: str, cfg: dict) -> str:
    """SELECT that builds certified_client_scorecard from the certified portfolio table `portfolio`."""
    b = cfg["business"]["client_bands"]
    w = cfg["business"]["health_score_weights"]
    return f"""
WITH agg AS (
  SELECT
    client_id,
    max(client_name)                                                    AS client_name,
    count(*)                                                            AS n_projects,
    count_if(status = 'Active')                                         AS n_active,
    count_if(status = 'Pending')                                        AS n_pending,
    count_if(status = 'Closed')                                         AS n_closed,
    count_if(performance_status = 'Performing')                         AS n_performing,
    count_if(performance_status = 'Watchlist')                          AS n_watchlist,
    count_if(performance_status = 'Past Due')                           AS n_past_due,
    count_if(performance_status = 'Completed')                          AS n_completed,
    count_if(performance_status = 'Exited at a loss')                   AS n_exited_at_loss,
    round(sum(total_approved_musd), 2)                                  AS approved_musd,
    round(sum(coalesce(disbursed_musd, 0)), 2)                          AS lifetime_disbursed_musd,
    round(sum(current_disbursed_exposure_musd), 2)                      AS current_disbursed_exposure_musd,
    round(sum(undisbursed_commitment_musd), 2)                          AS undisbursed_commitment_musd,
    round(sum(pipeline_unsigned_musd), 2)                               AS pipeline_unsigned_musd,
    round(sum(CASE WHEN performance_status = 'Past Due'  THEN disbursed_musd ELSE 0 END), 2) AS past_due_disbursed_musd,
    round(sum(CASE WHEN performance_status = 'Watchlist' THEN disbursed_musd ELSE 0 END), 2) AS watchlist_disbursed_musd,
    round(sum(expected_credit_loss_musd), 2)                            AS expected_credit_loss_musd,
    round(sum(CASE WHEN environmental_category = 'A'
                   THEN current_disbursed_exposure_musd + undisbursed_commitment_musd ELSE 0 END), 2) AS category_a_exposure_musd,
    round(avg(CASE WHEN status = 'Active' THEN internal_risk_rating END), 2) AS avg_risk_rating_active,
    max(CASE WHEN status = 'Active' THEN internal_risk_rating END)          AS max_risk_rating_active,
    count_if(status = 'Active' AND internal_risk_rating >= 5)               AS n_active_rating_5_6,
    round(sum(CASE WHEN status = 'Active' THEN internal_risk_rating * disbursed_musd END)
          / nullif(sum(CASE WHEN status = 'Active' THEN disbursed_musd END), 0), 2) AS exposure_weighted_risk_rating,
    round(avg(internal_risk_rating), 2)                                 AS avg_risk_rating_all,
    round(avg(CASE WHEN status = 'Active' THEN days_since_last_review END), 0) AS avg_days_since_review_active,
    max(CASE WHEN status = 'Active' THEN days_since_last_review END)    AS max_days_since_review_active,
    count_if(status = 'Active' AND mon_flag_review_overdue)             AS n_review_overdue_active,
    count_if(needs_review)                                              AS n_projects_needing_review,
    count_if(dq_max_severity = 'high')                                  AS n_high_severity_flags,
    count(DISTINCT country)                                             AS n_countries,
    count(DISTINCT industry)                                            AS n_industries,
    mode(industry)                                                      AS primary_industry,
    mode(region)                                                        AS primary_region,
    round(avg(CASE WHEN is_climate_related THEN 1.0 ELSE 0.0 END), 3)   AS climate_share
  FROM {portfolio}
  WHERE is_monitored
  GROUP BY client_id
),
country_exposure AS (
  SELECT client_id, country, sum(current_disbursed_exposure_musd) AS exposure
  FROM {portfolio}
  WHERE is_monitored AND status = 'Active'
  GROUP BY client_id, country
),
top_country AS (
  SELECT client_id,
         max(CASE WHEN rn = 1 THEN country END)                          AS top_country,
         round(max(CASE WHEN rn = 1 THEN exposure END) / nullif(sum(exposure), 0), 3) AS top_country_exposure_share
  FROM (SELECT *, row_number() OVER (PARTITION BY client_id ORDER BY exposure DESC, country) AS rn FROM country_exposure) r
  GROUP BY client_id
),
scored AS (
  SELECT a.*, t.top_country, t.top_country_exposure_share,
    round(a.current_disbursed_exposure_musd + a.undisbursed_commitment_musd, 2)                            AS exposure_affected_musd,
    round((a.past_due_disbursed_musd + a.watchlist_disbursed_musd) / nullif(a.current_disbursed_exposure_musd, 0), 3) AS distress_share,
    round(a.n_exited_at_loss / nullif(a.n_completed + a.n_exited_at_loss, 0), 3)                          AS closed_loss_rate
  FROM agg a LEFT JOIN top_country t ON a.client_id = t.client_id
),
banded AS (
  SELECT *,
    round({w['risk_rating']} * 100 * (6 - coalesce(exposure_weighted_risk_rating, avg_risk_rating_all)) / 5
        + {w['distress']} * 100 * (1 - coalesce(distress_share, 0))
        + {w['closed_loss']} * 100 * (1 - coalesce(closed_loss_rate, 0)), 1)                               AS health_score,
    CASE
      WHEN n_past_due >= {b['band_reduce_past_due']}
        OR coalesce(distress_share, 0) >= {b['band_reduce_distress_share']}
        OR coalesce(exposure_weighted_risk_rating, 0) >= {b['band_reduce_rating']}
        THEN 'REDUCE_OR_REVIEW'
      WHEN n_past_due = 0 AND n_watchlist = 0 AND coalesce(max_risk_rating_active, 9) <= {b['band_continue_max_rating']}
           AND coalesce(closed_loss_rate, 0) <= {b['band_continue_max_closed_loss']}
           AND n_active >= {b['band_continue_min_active']}
        THEN 'CONTINUE'
      ELSE 'MONITOR'
    END                                                                                                 AS band,
    concat_ws('; ',
      CASE WHEN n_past_due > 0 THEN concat(CAST(n_past_due AS STRING), ' Past Due') END,
      CASE WHEN n_watchlist > 0 THEN concat(CAST(n_watchlist AS STRING), ' Watchlist') END,
      CASE WHEN n_exited_at_loss > 0 THEN concat(CAST(n_exited_at_loss AS STRING), ' exited at a loss') END,
      concat('exposure-weighted rating ', coalesce(CAST(exposure_weighted_risk_rating AS STRING), 'n/a'), '/6'),
      concat(CAST(round(100 * coalesce(distress_share, 0), 1) AS STRING), '% of current exposure distressed')
    )                                                                                                   AS band_evidence
  FROM scored
)
SELECT *,
  rank() OVER (PARTITION BY band ORDER BY exposure_affected_musd DESC) AS materiality_rank_in_band
FROM banded
"""


# Signals in display order: (column, label shown to users, SQL condition on certified_client_scorecard)
def early_warning_signals(cfg: dict) -> list:
    e = cfg["business"]["early_warning"]
    return [
        ("sig_multiple_watchlist", "Multiple Watchlist projects", f"n_watchlist >= {e['min_watchlist_projects']}"),
        ("sig_high_risk_rating", "Internal risk ratings 5-6", f"n_active_rating_5_6 >= {e['min_active_rating_5_6']}"),
        ("sig_review_overdue", "Long time since last review", f"n_review_overdue_active >= {e['min_review_overdue']}"),
        ("sig_existing_past_due", "Existing Past Due projects", f"n_past_due >= {e['min_past_due']}"),
        ("sig_country_concentration", "Concentration in one country",
         f"n_active >= {e['concentration_min_active']} AND coalesce(top_country_exposure_share, 0) >= {e['concentration_share']}"),
    ]


def early_warning_sql(scorecard: str, cfg: dict) -> str:
    """SELECT that builds certified_early_warning from certified_client_scorecard (clients with Active exposure only)."""
    e = cfg["business"]["early_warning"]
    sigs = early_warning_signals(cfg)
    flags = ",\n    ".join(f"({cond}) AS {col}" for col, _, cond in sigs)
    count = " + ".join(f"CASE WHEN {col} THEN 1 ELSE 0 END" for col, _, _ in sigs)
    triggers = ",\n      ".join(f"CASE WHEN {col} THEN '{label}' END" for col, label, _ in sigs)
    return f"""
WITH s AS (
  SELECT client_id, client_name, primary_industry, primary_region, band, health_score,
    n_active, n_watchlist, n_past_due, n_active_rating_5_6, n_review_overdue_active, n_high_severity_flags,
    max_days_since_review_active, top_country, top_country_exposure_share,
    current_disbursed_exposure_musd, undisbursed_commitment_musd, exposure_affected_musd,
    past_due_disbursed_musd, watchlist_disbursed_musd, expected_credit_loss_musd,
    {flags}
  FROM {scorecard}
  WHERE n_active > 0
),
c AS (
  SELECT *, {count} AS signal_count,
    concat_ws('; ',
      {triggers}
    ) AS triggered_by
  FROM s
)
SELECT *,
  CASE WHEN signal_count >= {e['high_priority_min_signals']} THEN 'HIGH'
       WHEN signal_count >= {e['medium_priority_min_signals']} THEN 'MEDIUM'
       ELSE 'REVIEW' END                                                     AS priority,
  CASE WHEN signal_count >= {e['high_priority_min_signals']} THEN 'Escalate to the Credit Risk Committee'
       WHEN signal_count >= {e['medium_priority_min_signals']} THEN 'Schedule an updated portfolio review'
       ELSE 'Analyst investigation' END                                      AS suggested_action,
  'Credit Risk'                                                              AS review_owner
FROM c
WHERE signal_count > 0
"""
