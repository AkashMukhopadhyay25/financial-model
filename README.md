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
| `04_answers/ws1/ws1_answers.py` | WS1: certified answers to the 30 questions (+ detail lists) from `certified_investment_portfolio`, with SQL, assumption IDs, excluding-Dropped sensitivity figures, per-answer data-quality counts and 14 reconciliation checks → `answers_register` |
| `02_agent/01_genie_space.py` | Creates/updates the Genie space from code: certified table + `ref_assumptions` + `ops_dq_issues`, instructions, the certified WS1 SQL as examples and benchmarks |
| `02_agent/genie_paraphrases.yml` | 4 reviewed paraphrases per WS1 question and how to compare Genie's result with the certified answer |
| `02_agent/04_evaluate_genie.py` | Asks Genie every phrasing, re-runs its SQL, scores accuracy and consistency, adds flag counts per answer → `genie_eval_results`, `genie_eval_summary`, MLflow |
| `02_agent/scope_analyzer.py` | Works out which projects a generated SQL answer covers (project list, filters across CTEs/UNIONs, groups returned under HAVING/LIMIT) so the data-quality caveat is computed, not left to the model; tested in `tests/test_scope_analyzer.py` |
| `tests/` | Runs Stage 3's SQL locally on SQLite |
| `test_files/` | Deliberately broken files for testing and the demo |
| `data/` | Source CSVs and case files (not in git; copy them in yourself) |

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
