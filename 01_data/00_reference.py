# Databricks notebook source
# MAGIC %md
# MAGIC # 00_reference — assumptions and mappings are data, not hidden code
# MAGIC
# MAGIC Storing assumptions and mappings as tables means Genie, the agent, the app and the README all quote the **same**
# MAGIC definitions, and a CFO-office owner can change a rule without touching code.
# MAGIC
# MAGIC | Table | What it holds | How it is built |
# MAGIC |---|---|---|
# MAGIC | `ref_assumptions` | Business definitions A01–A24 applied to every answer | Rebuilt each run. Thresholds come from `config/pipeline_config.yml`; counts quoted in the text come from the validated tables, so the wording never drifts from the data. |
# MAGIC | `ref_market_outlook` | Curated, cited, dated external research for the Capital Allocation Agent (A24) | Rebuilt each run from `config/market_outlook.yml`. |
# MAGIC | `ref_region_mapping` | Region labels restated to the data-dictionary value (A06) | Rebuilt each run **from the projects contract's `standardize` block**, the one source of truth Stage 3 also uses. |
# MAGIC | `ref_product_vocabulary` | Financing instruments named in descriptions → Product Line (Q26) | Rebuilt each run. |
# MAGIC | `ref_text_feature_overrides` | Reviewer decisions on flagged text attributes (human in the loop) | **Created only if missing. Never replaced or emptied**: it holds human decisions. |
# MAGIC
# MAGIC Run after Stage 3 (`03_validate`), because the assumption texts quote counts from the validated tables.

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

from ifc_common import load_contracts  # noqa: E402  (00_setup is on sys.path after 00_config)

THR = CFG["thresholds"]
VAL = CFG["validation"]
CONTRACTS = load_contracts(CFG["_contracts_dir"])

# COMMAND ----------

# MAGIC %md ## Facts quoted in the assumption texts (read from the validated tables)

# COMMAND ----------


def fmt_date(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def read_facts() -> dict:
    """Counts and dates quoted in ref_assumptions, computed from the current validated tables."""
    q28 = Q28_ALLOCATION_THRESHOLD_MUSD
    p = spark.sql(f"""
        SELECT
          max(as_of_date)                                   AS reporting_date,
          min(as_of_date)                                   AS first_snapshot,
          count(DISTINCT as_of_date)                        AS n_snapshots,
          count(*)                                          AS n_projects,
          count(DISTINCT project_number)                    AS n_project_numbers,
          count_if(flag_signed_before_approval)             AS n_signed_before_approval,
          count_if(flag_under_allocated)                    AS n_under_allocated,
          count_if(flag_over_allocated)                     AS n_over_allocated,
          count_if(abs(total_approved_musd - (amt_loan_musd + amt_equity_musd + amt_guarantee_musd + amt_risk_mgmt_musd)) > {q28})
                                                            AS n_q28_gap,
          count_if(flag_outdated_record)                    AS n_outdated,
          count_if(flag_board_date_passed)                  AS n_board_date_passed
        FROM {T('validated_projects')}
    """).first().asDict()
    restated = {r["region_as_reported"]: r["n"] for r in spark.sql(f"""
        SELECT region_as_reported, count(*) AS n FROM {T('validated_projects')}
        WHERE region_as_reported <> region GROUP BY region_as_reported""").collect()}
    m = spark.sql(f"SELECT count_if(flag_review_overdue) AS n_review_overdue FROM {T('validated_monitoring')}").first()
    p["restated"] = restated
    p["n_review_overdue"] = m["n_review_overdue"]
    return p


# COMMAND ----------

# MAGIC %md ## Assumptions A01–A24
# MAGIC A01–A17 are the core definitions, refined where later analysis required it (A03, A06, A07, A08,
# MAGIC A11, A15, A17). A18–A24 are new: review overdue, Board date passed, quarantine vs flag, data contracts, early-warning signals,
# MAGIC capital-allocation ranking, curated external research.

# COMMAND ----------


def build_assumptions(cfg: dict, f: dict) -> list:
    """Rows (assumption_id, topic, statement, rationale, parameters). Pure Python: config + facts in, rows out."""
    thr, val, biz = cfg["thresholds"], cfg["validation"], cfg["business"]
    bands, w = biz["client_bands"], biz["health_score_weights"]
    tol = thr["amount_reconciliation_tolerance_musd"]
    q28 = biz["q28_allocation_threshold_musd"]
    ecl = biz["ecl_loss_rate"]
    rod = thr["review_overdue_days"]
    ca = biz["capital_allocation"]
    ew = biz["early_warning"]
    exemptions = thr.get("review_exemptions") or []
    rep = fmt_date(f["reporting_date"])
    restated = "; ".join(f'"{k}" ({v} projects)' for k, v in sorted(f["restated"].items())) or "none in the current data"
    std = CONTRACTS["projects"]["schema"]
    region_map = next(c for c in std if c["target"] == "region").get("standardize", {})
    region_map_txt = ", ".join(f'"{k}" -> "{v}"' for k, v in region_map.items())

    return [
        ("A01", "Join key",
         "Project Portfolio and Project Monitoring are joined on Project Url (one-to-zero-or-one). Projects are counted by Project Url.",
         f"Project Url is unique in both files. Project Number is not unique ({f['n_project_numbers']:,} distinct values across "
         f"{f['n_projects']:,} projects) and cannot identify a project.", ""),
        ("A02", "Reporting date",
         f'The reporting date is the latest As of Date in the data ({rep}). "Last N years" means an approval date after '
         "(reporting date minus N years) and on or before the reporting date.",
         "Answers must not change depending on the day they are run.", f"reporting.reference_date = {cfg['reporting']['reference_date']}"),
        ("A03", "Status filters",
         "Status filters are applied only where a question states them. A question that does not mention status includes every "
         "project, Dropped included. Where this choice moves the figure (Q1, Q2, Q5, Q9, Q10, Q11, Q17, Q20), the answer also "
         "reports the figure excluding Dropped projects as a sensitivity note.",
         "A literal, predictable rule; the question set states a status filter whenever it wants one (e.g. Q3, Q8, Q18). "
         "Dropped projects may have been Board-approved before cancellation, so both figures are shown.", ""),
        ("A04", "Approved by the Board",
         "A project counts as Board-approved when IFC Approval Date is present. For projects not yet approved, the Total column "
         "holds the proposed amount.",
         "Data dictionary definition of the Total column.", ""),
        ("A05", "Committed",
         "A project is committed once its legal agreements are signed (IFC Signed Date present) unless its Status is Dropped.",
         "Definition given in question 6.", ""),
        ("A06", "Region labels",
         f"Region labels that are not in the data dictionary are restated: {region_map_txt}. In the current data: {restated}. "
         "The label as received is kept in region_as_reported and the row carries flag_region_standardized (info).",
         "Otherwise regional totals split the same countries across two names. The mapping is defined once, in the projects "
         "data contract, and ref_region_mapping is generated from it.", "contracts/projects_contract.yml: region.standardize"),
        ("A07", "Lifecycle intervals",
         "Approval-to-signing-to-investment intervals use only records whose dates are in lifecycle order. "
         f"{f['n_signed_before_approval']} projects signed before approval are excluded from averages; they carry "
         "flag_signed_before_approval and are listed in the data-quality issues.",
         "A negative interval is a recording error, not a business fact.", ""),
        ("A08", "Product amounts",
         "Three amount measures are never mixed: Approved (Board total) for totals; Allocated (sum of the four product columns) "
         "for product mix only; Disbursed (monitoring) for exposure. Every project whose allocations differ from the Board "
         f"total by more than ${tol}M is flagged: {f['n_under_allocated']} under-allocated (warning) and "
         f"{f['n_over_allocated']} over-allocated (high). Question 28 reports gaps above ${q28:g}M "
         f"({f['n_q28_gap']} projects) using the gap itself, not the flags.",
         "The source cannot tell us which figure is right; the CFO Office must decide. Over-allocation is high severity "
         "because product totals would exceed what the Board approved.",
         f"thresholds.amount_reconciliation_tolerance_musd = {tol}; business.q28_allocation_threshold_musd = {q28}"),
        ("A09", "Current exposure",
         "Current disbursed exposure is the disbursed amount on Active projects. Closed projects have concluded; Pending "
         "projects have no disbursement.",
         "Data dictionary and glossary.", ""),
        ("A10", "Undisbursed commitments",
         "Active: approved minus disbursed (floored at 0). Pending and signed: the full approved amount. All other projects: 0. "
         "Disbursed below approved is normal (the undisbursed commitment); disbursed above approved is a high-severity flag.",
         "A signed agreement obliges IFC to fund; an unsigned Pending project is pipeline, reported separately.", ""),
        ("A11", "Expected credit loss",
         f"Past Due projects are treated as in default; expected loss = {ecl:.0%} of their disbursed amount.",
         "Simplified model given in the case brief.", f"business.ecl_loss_rate = {ecl}"),
        ("A12", "Text-derived attributes",
         "Renewable generation, capacity (MW), MSME focus and the product named in the description are extracted by an LLM and "
         "cross-checked against deterministic rules. Disagreements are flagged for human review; reviewer overrides in "
         "ref_text_feature_overrides take precedence.",
         "Free text is ambiguous; two independent methods plus review make the result trustworthy.",
         f"ai.llm_endpoint = {cfg['ai']['llm_endpoint']}"),
        ("A13", "New renewable generation",
         "The main purpose is to build, develop or expand the client's own renewable generation (solar, wind, hydro, "
         "geothermal). Excludes transmission and distribution, standalone battery storage, gas plants and rooftop solar for own "
         "use. Capacity is new MW only (GW x 1,000; for expansions only the added MW).",
         "Questions 13 and 24 ask about new generation, not anything mentioning renewables.", ""),
        ("A14", "MSME financing",
         'The main purpose is financing micro, small or medium enterprises (including "small firms" and "small companies") '
         "through a Finance-sector client. Excludes projects where SMEs are suppliers or incidental beneficiaries, are "
         "explicitly excluded, where loans go to households, and green lending only to corporate clients. Farms and factories "
         "expanding their own capacity are not MSME financing even when they benefit rural areas.",
         "Question 25 asks about financing for MSMEs. Review of 228 LLM/rule disagreements showed the LLM was right on "
         "small-firm lending phrasings and wrong on agribusiness, manufacturing and corporate-only lending; both corrections "
         "are encoded.", ""),
        ("A15", "Client bands",
         f"REDUCE_OR_REVIEW: {bands['band_reduce_past_due']}+ Past Due projects, or "
         f"{bands['band_reduce_distress_share']:.0%}+ of current exposure Past Due/Watchlist, or exposure-weighted risk rating "
         f"{bands['band_reduce_rating']} or worse. CONTINUE: no Past Due or Watchlist, every active rating "
         f"{bands['band_continue_max_rating']} or better, at most {bands['band_continue_max_closed_loss']:.0%} of closed "
         f"projects exited at a loss, and {bands['band_continue_min_active']}+ active projects. Otherwise MONITOR. "
         f"Health score = {w['risk_rating']:g} x rating score + {w['distress']:g} x (1 - distress share) + "
         f"{w['closed_loss']:g} x (1 - closed loss rate), on a 0-100 scale.",
         "Transparent thresholds the CFO Office can tune; they are policy parameters, not model outputs.",
         "business.client_bands; business.health_score_weights"),
        ("A16", "Currency",
         "All amounts are USD millions as supplied. The Currency field is informational; no FX conversion is applied.",
         "Data dictionary.", ""),
        ("A17", "Snapshot dates",
         f"Records carry one of {f['n_snapshots']} As of Dates ({fmt_date(f['first_snapshot'])} to {rep}). Each project's "
         f"latest available record is used. The {f['n_outdated']} records older than the reporting date are flagged "
         '"Outdated record – needs review" (flag_outdated_record) and are never excluded.',
         "Only one record per project exists; dropping older records would remove real projects from every total.", ""),
        ("A18", "Review overdue",
         "A periodic review is overdue for Active projects only, when days since last review exceed the limit for the "
         f"project's internal risk rating: rating 5-6 > {rod['rating_5_6']} days, 3-4 > {rod['rating_3_4']} days, "
         f"1-2 > {rod['rating_1_2']} days. Projects on the exemption list are excluded "
         f"({len(exemptions)} exempt). In the current data {f['n_review_overdue']} projects are overdue "
         "(monitoring flag review_overdue, warning).",
         "Riskier projects need closer monitoring. The data has no last-review date, only days since last review as supplied "
         "on the As of Date, so overdue status is derived. The day limits are policy parameters in config.",
         f"thresholds.review_overdue_days = {rod}; thresholds.review_exemptions = {len(exemptions)} entries"),
        ("A19", "Board date passed",
         "A Pending project that is not Board-approved and whose projected Board date is earlier than its As of Date is "
         f'"Board date passed, awaiting approval" ({f["n_board_date_passed"]} projects, flag board_date_passed, warning). '
         "A projected Board date in the future is normal and not flagged.",
         "These projects have slipped past their planned Board date; the Investment department should confirm the new date "
         "or drop them from the pipeline.", ""),
        ("A20", "Quarantine versus flag",
         "A row that cannot be used (missing required value, wrong type, value not allowed, wrong format, duplicate key, "
         "negative amount, monitoring row for an unknown project) is quarantined: removed from the validated tables and kept "
         "with its reasons. A row that is usable but questionable stays and carries a flag with a severity (info, warning, "
         "high) and an owner. If more than "
         f"{val['max_quarantine_share']:.0%} of a file's rows would be quarantined, the run stops and the previous validated "
         "tables stay in place.",
         "Removing usable rows would change Board totals silently; flags keep the figure and make the caveat visible. A high "
         "quarantine rate signals a systemic problem (e.g. a wrong date format), not a few bad rows.",
         f"validation.max_quarantine_share = {val['max_quarantine_share']}"),
        ("A21", "Data contracts and the schema gate",
         "Every source file is checked against its data contract (contracts/*.yml) before any value is read. An added, "
         "removed, renamed or duplicated column, an empty or header-only file, or an unrecognized file name is a hard stop: "
         "the file moves to held/, nothing downstream changes, and the job fails so the owner is alerted. To release a held "
         "file, correct it and drop it back into incoming/, or, if the change is intended, update the contract, bump its "
         "version and re-run.",
         "A changed file layout must never silently change Board figures. Contracts make the expected shape and every rule "
         "explicit and versioned.",
         f"schema_gate.allow_column_reorder = {cfg['schema_gate']['allow_column_reorder']}; contract versions: "
         + ", ".join(f"{k} {v['contract']['version']}" for k, v in sorted(CONTRACTS.items()))),
        ("A22", "Early-warning signals",
         "For every client with Active projects, five transparent signals are checked (certified_early_warning): "
         f"{ew['min_watchlist_projects']}+ Watchlist projects; {ew['min_active_rating_5_6']}+ Active projects rated 5-6; "
         f"{ew['min_review_overdue']}+ Active projects overdue for review (A18); {ew['min_past_due']}+ Past Due projects; "
         f"{ew['concentration_share']:.0%}+ of current exposure in one country (clients with "
         f"{ew['concentration_min_active']}+ Active projects). Priority: HIGH = {ew['high_priority_min_signals']}+ signals "
         f"(escalate), MEDIUM = {ew['medium_priority_min_signals']} (updated review), otherwise REVIEW (investigation). "
         "Industry concentration is not a signal: every client operates in a single industry in this data.",
         "Signals point an analyst to where to look; they are not a prediction of default and never trigger an automatic "
         "investment decision.",
         "business.early_warning"),
        ("A23", "Capital allocation ranking",
         f"Industries, regions and industry x region segments with {ca['min_active_projects']}+ Active projects are ranked on "
         "four credit metrics from the certified data (1 = best): distressed share of current exposure (Past Due + Watchlist, "
         "A09), expected credit loss / current exposure (A11), share of closed disbursed exited at a loss, and exposure-weighted "
         "internal risk rating. Overall rank = average of the four ranks. A segment holding more than "
         f"{ca['max_segment_share']:.0%} of current exposure is flagged as a concentration.",
         "Equal-weight ranks are transparent and do not depend on arbitrary weights; the Capital Allocation Agent explains the "
         "ranking but never computes it. Advice to the Credit Risk Committee, not an automatic allocation.",
         "business.capital_allocation"),
        ("A24", "External market research",
         "Market outlooks used by the Capital Allocation Agent come only from ref_market_outlook: curated reports (IMF, World "
         "Bank, IEA, GSMA, WTO, FAO), each with publisher, title, publication date, URL and a stance (prioritise / neutral / "
         "caution) for new commitments. They are shown beside the A23 ranking and never blended into it.",
         "A curated, versioned source list keeps every market claim cited and dated, and reviewable before the Board sees it; "
         "the agent does not browse the web.",
         "config/market_outlook.yml"),
    ]


# COMMAND ----------

FACTS = read_facts()
ASSUMPTIONS = build_assumptions(CFG, FACTS)
assert [a[0] for a in ASSUMPTIONS] == [f"A{i:02d}" for i in range(1, 25)], "Assumption IDs must be A01..A24 in order"

from pyspark.sql.types import StringType, StructField, StructType  # noqa: E402

_schema = StructType([StructField(c, StringType()) for c in
                      ["assumption_id", "topic", "statement", "rationale", "parameters"]])
spark.createDataFrame(ASSUMPTIONS, _schema).write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(T("ref_assumptions"))
spark.sql(f"COMMENT ON TABLE {T('ref_assumptions')} IS "
          "'Business definitions and assumptions (A01-A24) applied consistently across every answer, Genie and the agent. "
          "Thresholds come from pipeline_config.yml; counts are computed from the validated tables.'")
print(f"ref_assumptions: {len(ASSUMPTIONS)} rows")

# COMMAND ----------

# MAGIC %md ## External market research (A24), from `config/market_outlook.yml`

# COMMAND ----------

import os  # noqa: E402

import yaml  # noqa: E402
from ifc_common import read_text  # noqa: E402

_mo = yaml.safe_load(read_text(os.path.join(os.path.dirname(CFG["_config_path"]), "market_outlook.yml")))
MO_COLS = ["source_id", "publisher", "title", "published_date", "url", "industry", "region", "stance", "finding"]
MO_ROWS = [tuple(str(s[c]) for c in MO_COLS) + (str(_mo["retrieved_date"]),) for s in _mo["sources"]]
assert all(r[7] in ("prioritise", "neutral", "caution") for r in MO_ROWS), "stance must be prioritise, neutral or caution"
_schema = StructType([StructField(c, StringType()) for c in MO_COLS + ["retrieved_date"]])
(spark.createDataFrame(MO_ROWS, _schema)
 .selectExpr(*[c for c in MO_COLS if c != "published_date"], "CAST(published_date AS DATE) AS published_date",
             "CAST(retrieved_date AS DATE) AS retrieved_date")
 .write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(T("ref_market_outlook")))
spark.sql(f"COMMENT ON TABLE {T('ref_market_outlook')} IS "
          "'Curated external research for new-commitment decisions (A24): publisher, title, date, URL, stance, finding. "
          "Source: config/market_outlook.yml. Used by the Capital Allocation Agent; never blended into the A23 ranking.'")
print(f"ref_market_outlook: {len(MO_ROWS)} sources")

# COMMAND ----------

# MAGIC %md ## Region mapping (generated from the projects contract)

# COMMAND ----------

_proj = CONTRACTS["projects"]
_region = next(c for c in _proj["schema"] if c["target"] == "region")
_note = (f"Not a data-dictionary value; restated to the region every other record for those countries uses. "
         f"Source: projects contract v{_proj['contract']['version']} (region.standardize).")
REGION_ROWS = [(k, v, _note) for k, v in _region.get("standardize", {}).items()]

_schema = StructType([StructField(c, StringType()) for c in ["region_as_reported", "region", "note"]])
spark.createDataFrame(REGION_ROWS, _schema).write.mode("overwrite").option("overwriteSchema", "true") \
    .saveAsTable(T("ref_region_mapping"))
spark.sql(f"COMMENT ON TABLE {T('ref_region_mapping')} IS "
          "'Region labels restated to the data-dictionary value (assumption A06). Generated from the projects data contract.'")
print(f"ref_region_mapping: {len(REGION_ROWS)} rows")

# COMMAND ----------

# MAGIC %md ## Product vocabulary and reviewer overrides

# COMMAND ----------

# MAGIC %sql
# MAGIC CREATE OR REPLACE TABLE ref_product_vocabulary (phrase STRING, product STRING)
# MAGIC COMMENT 'Financing instruments named in project descriptions and the Product Line they belong to (used for Q26)';
# MAGIC INSERT INTO ref_product_vocabulary VALUES
# MAGIC ('long-term loan','Loan'), ('senior loan','Loan'), ('a-loan','Loan'), ('debt financing package','Loan'),
# MAGIC ('equity investment','Equity'), ('minority shareholding','Equity'), ('equity stake','Equity'), ('equity participation','Equity'),
# MAGIC ('credit guarantee facility','Guarantee'), ('partial credit guarantee','Guarantee'), ('risk-sharing guarantee','Guarantee'), ('guarantee','Guarantee'),
# MAGIC ('risk management facility','Risk Management'), ('currency hedging facility','Risk Management'),
# MAGIC ('interest rate swap','Risk Management'), ('derivative hedging product','Risk Management');
# MAGIC
# MAGIC -- Human-in-the-loop: a reviewer's decision on a flagged text attribute wins over both methods.
# MAGIC -- CREATE ... IF NOT EXISTS on purpose: this table holds human decisions and is never replaced.
# MAGIC CREATE TABLE IF NOT EXISTS ref_text_feature_overrides (
# MAGIC   project_url STRING, attribute STRING, value STRING, reviewer STRING, reviewed_at TIMESTAMP, note STRING)
# MAGIC COMMENT 'Reviewer decisions on flagged text attributes (attribute in: is_new_renewable_generation, new_capacity_mw, is_msme_financing, msme_target_group, described_product)';

# COMMAND ----------

# MAGIC %md ## Check

# COMMAND ----------

display(spark.sql(f"SELECT assumption_id, topic, statement, parameters FROM {T('ref_assumptions')} ORDER BY assumption_id"))  # noqa: F821
display(spark.sql(f"SELECT * FROM {T('ref_region_mapping')}"))  # noqa: F821
print("ref_product_vocabulary rows:", spark.table(T("ref_product_vocabulary")).count())
print("ref_text_feature_overrides rows (kept as is):", spark.table(T("ref_text_feature_overrides")).count())
