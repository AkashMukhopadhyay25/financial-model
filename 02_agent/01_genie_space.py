# Databricks notebook source
# MAGIC %md
# MAGIC # 01_genie_space — the Genie space, defined in code
# MAGIC
# MAGIC Creates (first run) or updates (later runs) the Genie space that answers portfolio questions in plain English.
# MAGIC Everything Genie knows is defined here and versioned in Git:
# MAGIC
# MAGIC | Part | Content |
# MAGIC |---|---|
# MAGIC | **Data** | `certified_investment_portfolio` (one row per project), `ref_assumptions` (A01–A21), `ops_dq_issues` (open data-quality issues). Nothing from earlier layers. |
# MAGIC | **Instructions** | The business definitions Genie must apply, with thresholds read from config. |
# MAGIC | **Example SQL** | The certified WS1 queries from `answers_register` (trusted answers Genie reuses for similar questions). |
# MAGIC | **Benchmarks** | The same 30 questions with their certified SQL, for Genie's built-in benchmark run. |
# MAGIC
# MAGIC After the first run, copy the printed space ID into `serving.genie_space_id` in `config/pipeline_config.yml` and
# MAGIC commit it, so later runs update the same space instead of creating a new one.
# MAGIC
# MAGIC Run after `04_answers/ws1/ws1_answers` (the example SQL comes from the certified answers).

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

import json
import uuid

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
SPACE_TITLE = "IFC Certified Investment Portfolio"
SPACE_DESCRIPTION = ("Ask questions about IFC's investment portfolio. Answers use the certified portfolio table, the business "
                     "definitions in ref_assumptions (A01-A21) and report data-quality caveats.")
TABLES = [T("certified_investment_portfolio"), T("ref_assumptions"), T("ops_dq_issues")]

rod = CFG["thresholds"]["review_overdue_days"]
reporting_date = spark.sql(f"SELECT max(reporting_date) FROM {T('certified_investment_portfolio')}").first()[0]

INSTRUCTIONS = f"""You answer questions for IFC's CFO Office about its investment portfolio. Amounts are USD millions.

Tables:
- {T('certified_investment_portfolio')}: one row per project with every attribute. Use it for every figure.
- {T('ref_assumptions')}: business definitions A01-A21. Name the IDs you applied.
- {T('ops_dq_issues')}: open data-quality issues per project (owner, severity, message). Use it when asked about data quality or why a project is flagged.

Definitions (always apply):
- Reporting date = max(reporting_date) = {reporting_date}. "Last N years" = approval_date > add_months(reporting date, -12*N) AND approval_date <= reporting date (A02). Never use current_date().
- Status (A03): filter on status only when the question states a status. Otherwise include every status, Dropped included. When no status is stated and the answer is an amount or a count, add one line with the same figure excluding Dropped (status <> 'Dropped').
- Board-approved = is_board_approved (A04). total_approved_musd is the Board total (the proposed amount if not yet approved).
- Committed = is_committed: signed and not Dropped (A05).
- Three amount measures, never mixed (A08): totals use total_approved_musd; product mix uses amt_loan_musd, amt_equity_musd, amt_guarantee_musd, amt_risk_mgmt_musd; exposure uses disbursed_musd, current_disbursed_exposure_musd, undisbursed_commitment_musd, expected_credit_loss_musd.
- "Board total differs from product allocations by more than $X" = abs(alloc_gap_musd) > X. Do not use flag_under_allocated or flag_over_allocated for this; they use a $0.01M tolerance.
- region is standardized (A06): Middle East includes North Africa, Latin America includes the Caribbean. For a sub-region such as North Africa, filter on country. Never group by region_as_reported.
- Years: approval_year, signed_year, invested_year, disclosed_year are calendar years; approval_fy etc. are IFC fiscal years (July-June, labelled by the June year). Use calendar years unless the question says fiscal year.
- Time between lifecycle steps: days_approval_to_signing, days_signing_to_investment, days_approval_to_investment. Invalid sequences are already null (A07).
- Text-derived attributes (A12-A14): is_new_renewable_generation, new_capacity_mw, is_msme_financing, msme_target_group, described_product. Never search project_description with LIKE.
- Projects are identified and counted by project_url (A01). project_number is NOT unique. In project lists show project_url, project_number and project_name.
- Overdue reviews: mon_flag_review_overdue (A18: Active only; risk rating 5-6 > {rod['rating_5_6']} days, 3-4 > {rod['rating_3_4']}, 1-2 > {rod['rating_1_2']}). Pending projects past their Board date: flag_board_date_passed (A19).
- Data quality: never exclude flagged rows. When an answer aggregates projects, also report for the same rows count_if(needs_review) and count_if(dq_max_severity = 'high'), and count_if(text_attributes_need_review) when text attributes are used.

Always show the SQL and name the assumption IDs applied."""


def hid() -> str:
    return uuid.uuid4().hex


# COMMAND ----------

# MAGIC %md ## Example SQL and benchmarks from the certified WS1 answers

# COMMAND ----------

certified = spark.sql(f"""
  SELECT question_id, question, sql_text FROM {T('answers_register')}
  WHERE workstream = 'WS1' AND question_id NOT LIKE '%detail%'
  ORDER BY question_id""").collect()
print(f"{len(certified)} certified WS1 queries")

def by_id(items: list) -> list:
    """The API requires every list of items with an id to be sorted by id."""
    return sorted(items, key=lambda x: x["id"])


space = {
    "version": 2,
    "data_sources": {"tables": [{"identifier": t} for t in sorted(TABLES)]},
    "instructions": {
        "text_instructions": by_id([{"id": hid(), "content": [INSTRUCTIONS]}]),
        "example_question_sqls": by_id([{"id": hid(), "question": [r.question], "sql": [r.sql_text]} for r in certified]),
    },
    "benchmarks": {"questions": by_id([{"id": hid(), "question": [r.question],
                                        "answer": [{"format": "SQL", "content": [r.sql_text]}]} for r in certified])},
}

# COMMAND ----------

# MAGIC %md ## Create or update the space

# COMMAND ----------

me = spark.sql("SELECT current_user()").first()[0]
body = {"title": SPACE_TITLE, "description": SPACE_DESCRIPTION, "warehouse_id": SQL_WAREHOUSE_ID,
        "serialized_space": json.dumps(space)}
if GENIE_SPACE_ID:
    result = w.api_client.do("PATCH", f"/api/2.0/genie/spaces/{GENIE_SPACE_ID}", body=body)
    space_id = GENIE_SPACE_ID
    print(f"Updated Genie space {space_id}")
else:
    result = w.api_client.do("POST", "/api/2.0/genie/spaces", body=dict(body, parent_path=f"/Users/{me}"))
    space_id = result["space_id"]
    print(f"Created Genie space {space_id}.\n"
          f"Put it in config/pipeline_config.yml -> serving.genie_space_id: {space_id}  (then commit), "
          f"so later runs update this space instead of creating another.")
host = spark.conf.get("spark.databricks.workspaceUrl", "")
print(f"Open it: https://{host}/genie/rooms/{space_id}")
