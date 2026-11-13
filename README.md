# IFC CFO Copilot — merged repository

This repository is mid-merge. Two rules:

| Where | What it is |
|---|---|
| **Everything outside `reference/`** | The real, working code. Today that is our data pipeline (stages 1–3). Files are added here as each merge phase is completed. |
| **`reference/teammate_original/`** | The teammate's solution exactly as he shared it. **Read-only.** Code is copied from here into the real folders during the merge, then updated. |

## What's in the real code today

| Path | Purpose |
|---|---|
| `CLAUDE.md` | Project context and every decision made so far (read first) |
| `MERGE_PLAN.md` | Step-by-step plan for merging the two codebases (phases 1–10) |
| `config/pipeline_config.yml` | All settings: location (`ifc_challenge.portfolio`), thresholds, AI, serving IDs, business parameters |
| `contracts/` | Data contracts: expected columns, quarantine rules, flag rules |
| `00_setup/00_config.py` | Loads the config; creates the schema, the `landing` volume and its folders; defines `T()`, `answer()`, `persist_answers()` |
| `00_setup/ifc_common.py` | Shared helpers every notebook imports: finds and loads the config, `T(cfg, name)`, contract loading |
| `01_data/00_reference.py` | Reference tables: assumptions A01–A21 (values from config and the data), region mapping from the contract, product vocabulary, reviewer overrides (never replaced) |
| `01_data/01_schema_gate.py` | Stage 1: blocks files whose columns don't match the contract |
| `01_data/02_load_raw.py` | Stage 2: loads accepted files into Raw tables, keeping history |
| `01_data/03_validate.py` | Stage 3: types, standardizes, quarantines and flags rows |
| `01_data/04_enrich.py` | Text features from descriptions: rules + cached LLM + reviewer overrides → `enriched_rule_features`, `enriched_llm_extractions`, `enriched_project_text_features` |
| `01_data/05_certify.py` | Builds `certified_investment_portfolio`: one row per project with monitoring, text attributes and every data-quality flag; column comments for Genie; layer tags |
| `01_data/06_dq_checks.py` | Portfolio-level checks (reconciliation raw → validated → certified, keys, structure, allowed values; blocking ones stop the job) → `ops_dq_checks`; reviewers' work list view `ops_dq_issues` |
| `00_setup/ifc_monthly.py` | Monthly history helpers: month folders, the load registry `ops_monthly_loads` (one active upload per month and source), `raw_*_current` views, which months need rebuilding |
| `01_data/07_snapshot_month.py` | Copies the month just certified into `certified_investment_portfolio_history`, replacing only that month; records it in `ops_monthly_snapshots` |
| `01_data/08_trends.py` | KPIs per month (`kpi_monthly`), month over month with Improving / Deteriorating / Stable (`kpi_month_over_month`, `kpi_latest_scorecard`), project-level changes (`project_month_changes`), SQL function `compare_months()` |
| `01_data/run_monthly_pipeline.py` | One click: gate → Raw → rebuild every changed month (latest last) → trends |
| `config/pipeline_config_monthly_dev.yml` | Dev config (`extends` the main one): runs everything in schema `portfolio_monthly_dev` |
| `test_files/make_demo_months.py` | Writes synthetic months 2026-07 … 2026-10 (and a corrected October) into the landing zone for testing and the demo |
| `04_answers/ws1/ws1_answers.py` | WS1: certified answers to the 30 questions (+ detail lists) from `certified_investment_portfolio`, with SQL, assumption IDs, excluding-Dropped sensitivity figures, per-answer data-quality counts and 14 reconciliation checks → `answers_register` |
| `tests/` | Runs Stage 3's SQL locally on SQLite |
| `test_files/` | Deliberately broken files for testing and the demo |
| `data/` | Source CSVs and case files (not in git; copy them in yourself) |

## Monthly history: upload, override, trends

**Upload a month.** In Catalog Explorer: `ifc_challenge` → schema → Volumes → `landing` → `incoming` → create a folder
named for the month (`2026-10`) → Upload the projects and monitoring files into it. The folder name is the reporting
month; file names only need to match the contracts. Then run `01_data/run_monthly_pipeline` (Run all).

**Correct a month.** Upload the corrected file into the same month folder and run the pipeline again. The new upload
becomes the active one for that month (`ops_monthly_loads.is_active`); the earlier upload stays in Raw, marked
superseded. Only that month is rebuilt in `certified_investment_portfolio_history`; every other month is untouched.

**Latest data** = the highest month that has both files. `certified_investment_portfolio` (WS1, Genie) always shows it,
even when an older month is back-filled or corrected.

**Trends.**
- `kpi_latest_scorecard`: the latest month vs the previous one, worst first.
- `kpi_month_over_month`: every month, with the same comparison by region, industry, product line and department.
- `project_month_changes`: the projects behind each movement.
- Any two months: `SELECT * FROM compare_months('2026-07', '2026-10', 'Region')`.

KPIs, their "better" direction and the materiality threshold are in `trends` in the config.

**Try it without touching the team schema.**
1. Set the `config_path` widget to `config/pipeline_config_monthly_dev.yml`.
2. Run `test_files/make_demo_months` (step `generate`), then `01_data/run_monthly_pipeline`.
3. Run `make_demo_months` again with step `reupload_october`, then the pipeline again.

## What will move over from `reference/teammate_original/` during the merge

| His file | Becomes (real code) | Merge phase |
|---|---|---|
| `00_setup/00_config.py` | merged into our `00_setup/00_config.py` | 1 |
| `01_data/01_load_and_prepare.py` §2 | `01_data/00_reference.py` | 3 |
| §4 | `01_data/04_enrich.py` | 4 |
| §5–6 | `01_data/05_certify.py` | 5 |
| §7–8 | `01_data/06_dq_checks.py` | 6 |
| §1, §3 | **not used**: replaced by our stages 1–3 | — |
| `04_answers/ws1, ws2, ws3` | `04_answers/...` | 7 |
| `02_agent/*` | `02_agent/...` (+ new `04_evaluate_genie.py`) | 8 |
| `03_demo/04_app.py`, `app.yaml`, `requirements.txt` | same paths | 9 |
| `README.md`, `WALKTHROUGH.md`, `IMPLEMENTATION_STRATEGY.md`, `assets/` | merged into this README and docs | 10 |

When the merge is finished, `reference/` can be deleted.
