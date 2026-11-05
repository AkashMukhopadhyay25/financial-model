# IFC CFO Office — Portfolio Intelligence (Agentic Innovation Challenge)

Context for anyone (human or Claude) continuing this project. Read this first, then `MERGE_PLAN.md`.

## Current state (2026-11-04)
This repo combines **two codebases** that are being merged. **Rule: everything outside `reference/` is the real code; `reference/teammate_original/` is the teammate's solution, read-only.**
- **Real code today (ours):** contract-driven pipeline (schema gate → Raw → Validated): `00_setup/`, `01_data/01–03`, `contracts/`, `config/`, `tests/`, `test_files/`. Stages 1–2 ran on Databricks under the old catalog `ifc_cfo`; Stage 3 was tested locally and may not yet have run on Databricks.
- **Teammate's (reference only):** end-to-end solution (WS1–WS3 answers, text enrichment, final tables, UC-function tools, CFO Decision Advisor agent, Streamlit app, evaluation, docs). During each merge phase, copy the relevant file from `reference/teammate_original/` into its real path (see the table in `README.md`), then update it. Never edit `reference/`.

**Phase 1 passed on Databricks (2026-11-04) and is merged to `master`. Phase 2 passed on Databricks (2026-11-04): 5,000 / 3,768 rows, 0 quarantined, all 22 flags `same` as profiling. Merged to `master`. Phase 3 passed on Databricks (2026-11-05): `ref_assumptions` A01–A21, `ref_region_mapping` from the contract, 16 vocabulary rows, overrides untouched. Ritvik's three `ref_*` tables were replaced with the user's approval (no backup). Merged to `master`. Phase 4 passed on Databricks (2026-11-05): 0 LLM calls (all 5,000 cached results carried over from `llm_text_extractions`); rule new-renewable = 277 (T02); 91 text rows need review (89 product, 1 capacity, 1 renewable); identical to the teammate's `gold_project_text_features` on every attribute. Merged to `master`. Phase 5 passed on Databricks (2026-11-05): `certified_investment_portfolio` 5,000 rows / 100 columns, all commented; status 1302/1233/1233/1232; review overdue 324; Board date passed 237; Q28 gap 146; needs_review 1,260 (78 high); identical to the teammate's `gold_portfolio` on every shared column. Merged to `master`. Phase 6 passed on Databricks (2026-11-05): 72 checks in `ops_dq_checks`, all pass (35 blocking: R reconciliation raw = validated + quarantined = certified for rows and every amount column, K keys, S structure, V allowed values; plus F first-delivery, D flag counts, T text). `ops_dq_issues` lists 1,555 open issues by owner. Next: phase 7 (WS1 only); check `answers_register` contents with the user before writing to it.** Follow `MERGE_PLAN.md` phase by phase; the user tests each phase on Databricks before the next. Source data for local tests is in `data/` (git-ignored).

**Workspaces:** the target is the team workspace `dbc-83823297-5832` (catalog `ifc_challenge` already exists there, owned by Ritvik Kohli, who must grant access). The old `ifc_cfo` catalog is in a different workspace, so Stages 1–2 run fresh here. Ritvik's live copy of his code is at `/Workspace/Users/ritvik.kohli@rotman.utoronto.ca/ifc-cfo-copilot`. It is newer than `reference/` in `cfo_agent.py`, `03_build_agent.py` and `04_app.py`; pick those changes up in phases 8–9.

## The case
- Competition: Accenture/BTA "Forward Deployed: Agentic Innovation Challenge". Client: IFC CFO Office. Platform: **Databricks** (Unity Catalog, Genie, Databricks Apps). Submission deadline Sun Nov 15, 11:59 p.m. EST (see `IMPLEMENTATION_STRATEGY.md`).
- Client pain: two departments showed the Board different figures for the same measure. They want **consistent figures regardless of phrasing, traceability, and flags for human review**. The brief: "where a question or the data is ambiguous, state the assumptions and apply them consistently."
- Workstreams: **WS1** = 30 portfolio questions (`data/IFC_portfolio_questions.txt`), with the SQL used; **WS2** = integrated view with monitoring data (two Board questions); **WS3** = decision support (which clients to back or review).
- Data (synthetic): `synthetic_ifc_projects_5000.csv` (5,000 rows, 24 cols), `synthetic_project_monitoring.csv` (3,768 rows, 10 cols), `IFC_data_dictionary.xlsx`.
- Scoring: data quality 15 pts; agentic prototype 25; architecture & governance 18; the 4 [Challenge] questions (13, 24, 25, 26) separate teams.

## Final decisions (see MERGE_PLAN §0)
- **Location:** catalog `ifc_challenge`, schema `portfolio`. Layers are **name prefixes**: `raw_*` → `validated_*` → `enriched_*` → `certified_*`, plus `ref_*` and `ops_*`. The final layer was renamed from `defined_*` by the user; the main table is **`certified_investment_portfolio`** (was his `gold_portfolio`).
- **Scope (2026-11-05): WS1 first, end to end and thorough.** Phases 5 (portfolio table only), 6, 7 (WS1 only), slim 8 (Genie + 4-phrasing evaluation + flag counts per answer; no agent). WS2, WS3, the client scorecard, the agent, the app and packaging are postponed until WS1 works.
- **Never use bronze/silver/gold** in code, comments or docs (user preference). The README may note the mapping to medallion once.
- **Column names:** ours from the contracts (`amt_loan_musd`, `amt_equity_musd`, `amt_guarantee_musd`, `amt_risk_mgmt_musd`, …), applied everywhere.
- **Allocation flags** at $0.01M: under-allocated = warning (72), over-allocated = high (78). **Q28** uses its own `abs(alloc_gap_musd) > 1` → 146. Never filter Q28 on the flag.
- **Status default (A03):** a question that names no status includes all statuses, Dropped included. This follows the question set, which states filters explicitly whenever it wants them (Q3, Q8, Q18, Q25, Q27, Q30 exclude Dropped). For Q1, Q2, Q5, Q9, Q10, Q11, Q17, Q20, also store the excluding-Dropped figure as a sensitivity note (e.g. Q1 $52,376M vs $42,661M; 738 Dropped projects were Board-approved).
- **Trust levels:** his statuses map to colors: VALIDATED = Green, REVIEW_RECOMMENDED = Amber, HUMAN_REVIEW_REQUIRED = Red; reasons are always listed. No numeric "confidence score".
- The **app/agent, not Genie, guarantees caveats**: after Genie returns SQL, count flagged rows in scope deterministically (MERGE_PLAN phase 8.3).
- **Evaluation:** certified answers in `answers_register` + reconciliation checks + **paraphrase consistency** (4 phrasings per WS1 question; MERGE_PLAN phase 8.5).

## Pipeline (merged target)
`00_setup/00_config` → `01_data/00_reference` → `01_schema_gate` → `02_load_raw` → `03_validate` → `04_enrich` → `05_certify` → `06_dq_checks`, then `04_answers/ws1–3`, then `02_agent/*`, then the app. Orchestrated by a Databricks Asset Bundle (`databricks.yml`, to be created).

What our stages do (already built):
- **Schema gate:** header-only check against the contract. **Hard stop** (file moved to `held/`, logged, job fails on purpose to trigger the failure email) for an added, removed, renamed or duplicate column, an empty file, a header-only file, or an unrecognized file name. A reorder is a warning (configurable). Renames are diagnosed by similarity. Duplicates are skipped by SHA-256.
- **Raw:** all values kept as text, renamed to contract targets, with audit columns (`_load_id, _loaded_at, _source_file, _file_sha256, _contract_version, _source_row_number`). **Appended** (history kept); `<table>_current` view = latest load. Row-count reconciliation happens before writing; a broken-quote file is rejected with nothing written.
- **Validate:** rules are SQL inside the contracts; the notebook generates and runs it (`${threshold}` from config, `{valid}` = all valid rows).
  - Quarantine = unusable row: missing required value, bad type, value not allowed, bad pattern, duplicate key, negative amount, monitoring row whose project is unknown.
  - Flags = row kept, with severity info/warning/high and an owner; rolled up into `needs_review`, `dq_max_severity`, `review_owners`, `dq_messages`.
  - The run **stops without replacing tables** if more than 5% of rows would be quarantined.
  - Generated SQL is saved for audit.

## Key data facts
- **Project Number is NOT unique** (3,559 distinct / 5,000). Joining on it inflates monitoring 3,768 → 6,477. **Join key = `project_url`.** Count projects by URL.
- Monitoring covers every non-Dropped project (1,233 Active + 1,233 Pending + 1,302 Closed) and is internally consistent.
- 475 descriptions span several lines; naive CSV readers, including the Databricks upload UI, break on them.
- Project names repeat (189 names reused).
- Regions: 9 raw values → 7. The dictionary's "Middle East" already includes North Africa (Egypt, Morocco, Tunisia, Algeria, Libya; 200+ rows); the 21 "Middle East & North Africa" rows are the same countries spelled differently. North Africa questions must filter by country, not region (explained to and agreed with the user). "Latin America & Caribbean" and "Middle East & North Africa" are standardized (43 rows); North America = 5 Canada rows.
- Dates:
  - approval 2013-08-13..2026-06-27;
  - 5 As of Date snapshots, 2025-06-30..2026-06-30; reporting date = 2026-06-30;
  - projected Board date can be in the future (319 rows).
- Days since last review range 3..818. The **median rises with risk rating** (47 days → 100), so the riskiest projects are reviewed least recently. 119 of 170 high-risk Active projects (70%) are overdue.
- Flag counts on the first delivery:

  | Flag | Count |
  |---|---|
  | region standardized | 43 |
  | under-allocated | 72 |
  | over-allocated | 78 |
  | signed before approval | 37 |
  | invested without signing | 16 |
  | outdated record | 607 |
  | Board date passed | 237 (= Q12) |
  | pending without Board date | 14 |
  | description missing | 31 |
  | North America | 5 |
  | invested before signed | 0 |
  | review overdue | 324 |

  0 quarantined.

## Agreed business definitions
- **Three amount measures, never mixed:**
  - **Approved** = `total_approved_musd`, the Board figure, used for totals;
  - **Allocated** = the sum of the 4 product columns, used for product mix only;
  - **Disbursed** = monitoring `disbursed_musd`.

  Disbursed > Approved = high flag. Disbursed < Approved is normal; the gap is the **undisbursed commitment** (his A10), not a flag.
- **"Outdated record – needs review"** = `as_of_date` < latest (607). Never excluded.
- **Review overdue:** Active only, risk-tiered in config (5–6 > 30 days, 3–4 > 90, 1–2 > 180), with a `review_exemptions` list. No last-review date exists; it can only be derived (an assumption).
- **Board date passed:** Pending, unapproved, `projected_board_date` < `as_of_date`.
- **Teammate assumptions A01–A17 are kept** (`ref_assumptions`): reporting date, committed = signed and not Dropped, current exposure = Active disbursed, ECL = 60% of Past Due disbursed, client bands (A15), lifecycle intervals exclude invalid sequences (A07), text-attribute definitions (A12–A14). New A18–A21 are added per MERGE_PLAN phase 3.
- Text traps:
  - MWh storage is not generation capacity;
  - GW must be converted to MW;
  - transmission lines that connect other sponsors' farms don't count as new generation;
  - rooftop solar for own use doesn't count;
  - "rather than SMEs" and "Unlike the bank's SME programs" are negations;
  - descriptions can name several products (use the main one, as in "X alongside a smaller Y");
  - 31 blank descriptions must be counted.

## Working conventions
- The user is new to Databricks: give exact click paths, explain plainly, keep changes small and testable.
- **The user validates each phase on Databricks before the next.** Don't jump ahead.
- Never drop or overwrite `ref_text_feature_overrides`, `enriched_llm_extractions` (or his `llm_text_extractions`), `answers_register`, `agent_audit_log` or `raw_*` without asking. **No full LLM extraction without explicit approval**; test with 5 rows first.
- Notebooks work on Databricks and locally. The config is found as: env var `IFC_PIPELINE_CONFIG` → widget `config_path` → `<repo root>/config/pipeline_config.yml`. Config and contracts deploy with the code, not to the volume; the volume holds data files only. Shared helpers live in `00_setup/ifc_common.py` (`T(cfg, name)`); `00_config` exposes `T(name)`. `tests/sqlite_dialect.py` runs Stage 3's generated SQL on SQLite against `data/`.
- Keep Python 3.11-compatible (no nested same-quote f-strings).
- Bump a contract's `version` and changelog on any rule change.
- Settings live in `config/pipeline_config.yml` only; nothing else hard-codes a catalog, threshold, endpoint or ID.
- When a decision changes, update this file and `MERGE_PLAN.md` §0.

## Next step
Phase 7 (WS1 answers), then slim 8. Cleanup plan for the teammate's old tables (agreed with the user): archive to `ifc_challenge.archive_teammate` then delete, with Ritvik's OK; pipeline tables (bronze/silver/gold portfolio, text features, his dq tables) after phase 8 points Genie at our tables; WS2/WS3/agent tables only once WS2/WS3 is decided. Databricks adds a `# /// script` environment header to a notebook when its Environment panel is changed in the UI; in the Git folder that blocks pulls until the change is discarded. Contracts are v1.3.0: they support `keep_original_as` (column option) and `derived_columns`. `serving.sql_warehouse_id` is set to the team workspace's Serverless Starter Warehouse (`b015ec4996eb0dd9`, verified); `genie_space_id` stays empty until phase 8. `ai.llm_extraction_limit` defaults to 5 (smoke-test size). Before deploying, set up the Databricks CLI and Asset Bundles with the user.
