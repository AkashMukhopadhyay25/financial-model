# Merge plan: our governed pipeline + the teammate's end-to-end solution

Goal: one codebase in `ifc_challenge.portfolio` that keeps the teammate's complete WS1–WS3, agent and app, and
replaces his single-run data prep with our contract-driven pipeline (schema gate → Raw → Validated), then adds the
pieces neither side finished.

Sources in this repo (see `README.md`):
- **Everything outside `reference/` is the real code.** Today it holds only our Stage 1–3 pipeline.
- `reference/teammate_original/`: his code, **read-only**. In each phase, copy the files that phase needs from here into their
  real paths (§2 layout), then update them. Never edit `reference/`.

Work through the phases in order. Each phase ends with an acceptance check. **The user tests each phase on
Databricks before the next starts.**

---

## 0. Decisions (final; do not reopen without asking the user)

| Topic | Decision |
|---|---|
| Location | Catalog `ifc_challenge`, schema `portfolio` (one schema). Layers are **name prefixes**. |
| Layer names | `raw_*` → `validated_*` → `enriched_*` → `certified_*`. Never bronze/silver/gold, in code, comments or docs. (The final layer was first called `defined_*`; renamed to `certified_*` by the user on 2026-11-05. The main table is `certified_investment_portfolio`.) |
| Scope (2026-11-13) | The user asked for a FastAPI + React Databricks App (`app/`) built from their mockups, **all pages live**. Phase 9 is therefore done as `app/` (not the Streamlit `03_demo/04_app.py`), and WS2/WS3 + client scorecard + early warning (A22, `01_data/07_client_views`) are built now. The LLM agent stays postponed; the app uses the Genie space plus the deterministic trust check (phase 8.3, `app/backend/trust.py`). |
| Scope (2026-11-05) | **WS1 first, end to end:** phases 5 (portfolio table only), 6, 7 (WS1 only) and a slim 8 (Genie space + paraphrase evaluation + flag counts per answer, no agent). WS2, WS3, the client scorecard, the agent, the app and packaging are **postponed**, not dropped; decide after WS1 works. |
| Column names | **Ours** from the contracts. His `loan_musd, equity_musd, guarantee_musd, risk_mgmt_musd` become `amt_loan_musd, amt_equity_musd, amt_guarantee_musd, amt_risk_mgmt_musd` **everywhere**, including SQL strings, UC functions, the app, Genie instructions, column comments, README and answers. All other source column names already match. |
| Allocation flags | Tolerance **$0.01M** (config `amount_reconciliation_tolerance_musd`). Under-allocated = warning (72), over-allocated = high (78). |
| Q28 | Uses its own threshold: `abs(alloc_gap_musd) > 1` → **146** projects. Never filter Q28 on the flag. |
| Status default (A03) | Literal: a question that names no status includes every status, Dropped included. For the questions it affects (**Q1, Q2, Q5, Q9, Q10, Q11, Q17, Q20**), also store the excluding-Dropped figure as a sensitivity note. E.g. Q1 $52,376M incl. vs $42,661M excl.; 738 Dropped projects were Board-approved before cancellation. |
| Join key | `project_url` only. `project_number` is never a key. |
| Review overdue | Active only, risk-tiered from config: rating 5–6 > 30 days, 3–4 > 90, 1–2 > 180 → 324 projects. |
| Naming of stale | "Outdated record – needs review" (`flag_outdated_record`), never "stale". |
| Tolerance-free facts | `expected_initial` counts stay in contracts as **information**. Nothing blocks on a hard-coded row count or dollar total. |

## 1. Target names (old → new)

| Teammate | Merged |
|---|---|
| volume `raw_files` | volume `landing` with folders `incoming/ accepted/ held/ loaded/` |
| `bronze_projects`, `bronze_monitoring` | `raw_projects`, `raw_monitoring` + views `raw_projects_current`, `raw_monitoring_current` |
| `silver_projects`, `silver_monitoring` | `validated_projects`, `validated_monitoring` |
| — | `validated_projects_quarantine`, `validated_monitoring_quarantine` |
| `dq_issue_log` | `validated_projects_dq_issues`, `validated_monitoring_dq_issues` + view `ops_dq_issues` (UNION of both + text-review issues) |
| `rule_text_features` | `enriched_rule_features` |
| `llm_text_extractions` | `enriched_llm_extractions` (**keep its rows if the table exists: the LLM run cost ~60 min**) |
| `gold_project_text_features` | `enriched_project_text_features` |
| `gold_portfolio` | `certified_investment_portfolio` |
| `gold_client_scorecard` | `certified_client_scorecard` (postponed with WS3) |
| `dq_results` | `ops_dq_checks` (portfolio-level assertions) and `ops_dq_run_summary` (per-rule counts from Stage 3) |
| `ops.schema_gate_log`, `ops.raw_load_log` | `ops_schema_gate_log`, `ops_raw_load_log` |
| `ref_assumptions`, `ref_region_mapping`, `ref_product_vocabulary`, `ref_text_feature_overrides` | unchanged names |
| `answers_register`, `ws3_recommendations`, `agent_audit_log`, `genie_benchmark` | unchanged names |
| UC functions (7) | unchanged names; bodies updated to new tables/columns |

His row-level flags map to ours:

| His column | Ours |
|---|---|
| `dq_region_restated` | `flag_region_standardized` (+ new column `region_as_reported`) |
| `dq_signed_before_approval` | `flag_signed_before_approval` |
| `dq_invested_without_signing_date` | `flag_invested_without_signing` |
| `dq_invested_before_signed` | **add** to contract as `flag_invested_before_signed` (warning, Data team, expected 0) |
| `dq_allocation_gap` (> $1M) | `flag_under_allocated` / `flag_over_allocated` (> $0.01M); Q28 uses `alloc_gap_musd` directly |
| `dq_stale_snapshot` | `flag_outdated_record` |
| `dq_risk_rating_out_of_range` (monitoring) | quarantine (allowed values 1–6), already in contract |

## 2. Repository layout (matches the brief's required folders)

```
ifc-cfo-copilot/
  CLAUDE.md  MERGE_PLAN.md  README.md  databricks.yml  app.yaml  requirements.txt
  config/pipeline_config.yml          # single source of settings (see phase 1)
  contracts/projects_contract.yml  contracts/monitoring_contract.yml
  00_setup/00_config.py               # creates schema + volume + folders; loads YAML; exposes T(), answer(), persist_answers()
  01_data/
    00_reference.py                   # ref_* tables (from his notebook §2) + ref_region_mapping GENERATED from the contract
    01_schema_gate.py                 # ours
    02_load_raw.py                    # ours
    03_validate.py                    # ours
    04_enrich.py                      # his §4 (rules + LLM + overrides), reading validated_projects
    05_certify.py                     # his §5–6 (certified_investment_portfolio, [certified_client_scorecard], comments, tags) + our flags
    06_dq_checks.py                   # his §7–8 checks, made data-driven; writes ops_dq_checks; blocks on failure
  02_agent/ 02_agent_capabilities.py  03_build_agent.py  cfo_agent.py  04_evaluate_genie.py (new)
  03_demo/04_app.py
  04_answers/ws1/ws1_answers.py  ws2/ws2_board_questions.py  ws3/ws3_client_recommendations.py
  assets/architecture_diagram_agentic_solution.svg (+ make_architecture_diagram.py)
  tests/ sqlite_dialect.py  README.md        test_files/  (broken demo files)
  reference/teammate_original/       # untouched
```

---

## Phase 1: Configuration and setup

1. **One config file.** Extend `config/pipeline_config.yml`:
   - `environment`: `catalog: ifc_challenge`, `schema: portfolio`, `volume: landing`; `landing_root` derived as `/Volumes/{catalog}/{schema}/{volume}`.
   - `ai`: `llm_endpoint`, `run_llm_extraction`, `llm_extraction_limit`, `llm_batch_size`, `llm_parallelism` (from his `00_config`).
   - `serving`: `sql_warehouse_id`, `genie_space_id`, `uc_model_name`. Leave them **empty** with a comment. His IDs belong to his personal workspace and won't work in the team workspace.
   - `business`: `ecl_loss_rate: 0.60`, `q28_allocation_threshold_musd: 1.0`, the client-band thresholds from his A15 (`band_reduce_past_due`, `band_reduce_distress_share`, `band_reduce_rating`, `band_continue_max_rating`, `band_continue_max_closed_loss`, `band_continue_min_active`), health-score weights (0.4/0.4/0.2).
   - Keep `thresholds`, `validation`, `schema_gate`, `landing_zone`, `reporting` as they are.
2. **Config location.** With Asset Bundles, `config/` and `contracts/` deploy as workspace files next to the notebooks (versioned in git), so read them from the repo, not the volume. Each notebook resolves `CONFIG_PATH` as: env var `IFC_PIPELINE_CONFIG` → notebook widget → `<repo root>/config/pipeline_config.yml`, found relative to the notebook's working directory. **Verify** that the working directory is the notebook's folder on the workspace's runtime; if not, use `dbutils.notebook.entry_point...notebookPath()` to build the path. The volume holds data files only.
3. **Our notebooks:** replace `full_table_name(cfg, "raw.projects")` style with `T("raw_projects")` = `{catalog}.{schema}.{name}`. Contract `targets` become bare names (`raw_projects`, `validated_projects`, …); `lookup.table: validated_projects`. Replace `ops_schema` with table names `ops_schema_gate_log`, `ops_raw_load_log`, `ops_dq_run_summary`. Bump both contracts to **v1.2.0** with a changelog line.
4. **`00_setup/00_config.py`:** keep his structure (`T()`, `answer()`, `persist_answers()`, `DECLARE OR REPLACE VARIABLE ecl_loss_rate`), but load values from the YAML instead of hard-coding them. Create the schema, the volume `landing` and its four folders. Keep his `try/except` on `CREATE CATALOG`.
5. **Extend `answer()`** with an optional `sensitivity_sql` and `sensitivity_label` (e.g. "Excluding Dropped"). Store both, plus the sensitivity result preview, in `answers_register` (new columns `sensitivity_label`, `sensitivity_sql`, `sensitivity_preview_json`). Also add `assumption_ids` (comma list, e.g. `A02,A03`).

**Accept:** `00_config` runs; every later notebook gets names only from config.

## Phase 2: Stages 1–3 on the new location

1. Update Stage 1–3 code per phase 1.3. No logic changes beyond:
   - **Contract:** add `flag_invested_before_signed` (when `invested_date < signed_date`).
   - **Validated output:** also emit `region_as_reported` (= the original value; today only `region__original` exists internally).
   - **Validated output:** emit `is_climate_related` boolean on monitoring (his column), derived from `climate_flag`.
2. **Do not** coalesce null product amounts to 0 (he did). They are `required` in the contract, so a blank is quarantined.
3. Run `tests/sqlite_dialect.py` against Stage 3 after the edits: the counts must still equal the `expected_initial` values.

**Accept:** gate passes both files; `raw_*` = 5,000 / 3,768; `validated_*` = 5,000 / 3,768, 0 quarantined; `ops_dq_run_summary` shows every flag `same` as profiling.

## Phase 3: Reference tables (`01_data/00_reference.py`)

1. Move his `ref_assumptions`, `ref_product_vocabulary`, `ref_text_feature_overrides` here. **Keep `ref_text_feature_overrides` as `CREATE TABLE IF NOT EXISTS`**: it holds human decisions.
2. Generate `ref_region_mapping` **from the contract's `standardize` block**, so there is one source of truth.
3. Update `ref_assumptions`:
   - A06: point to `region_as_reported`.
   - A08: product mix uses allocations, totals use the Board total; all gaps above $0.01M are flagged (150: 72 under, 78 over); Q28 reports gaps above $1M (146).
   - A17: wording "Outdated record – needs review".
   - A03: add the sensitivity-note rule.
   - Add **A18** review overdue (risk tiers, Active only, exemptions list, values read from config); **A19** Board date passed (Pending, unapproved, projected date before as-of date); **A20** quarantine vs flag policy and the 5% systemic-failure stop; **A21** data contracts and the schema gate (what a hard stop means and how to release a held file).
   - Thresholds in A15/A18 should be generated from config values, not typed twice.

**Accept:** `SELECT * FROM ref_assumptions` shows A01–A21, with numbers matching config.

## Phase 4: Enrich (`01_data/04_enrich.py`)

1. Port his §4 unchanged in logic, reading `validated_projects` (not silver).
2. `description_clean` (his whitespace-normalized text) is computed here.
3. **Preserve LLM cache.** If `ifc_challenge.portfolio.llm_text_extractions` exists from his runs, copy its rows into `enriched_llm_extractions` once (`INSERT … SELECT` where not already present) before extraction, so only new or changed descriptions hit the model. The cache key (`project_url`, `sha2(description_clean)`) must stay the same, so `description_clean` must be computed exactly as he did.
4. Smoke test first with `llm_extraction_limit: 5`. **Never run the full extraction without the user's go-ahead.**

**Accept:** the T02 rule count is 277; disagreements land in `enriched_project_text_features.needs_review`.

## Phase 5: Certify (`01_data/05_certify.py`)

1. Port his `gold_portfolio` → `certified_investment_portfolio`, built from `validated_projects` LEFT JOIN `validated_monitoring` (on `project_url`) LEFT JOIN `enriched_project_text_features`. Use `amt_*` names.
2. Derived columns computed here (were in his silver): `product_alloc_sum_musd`, `alloc_gap_musd`, `product_count`, `is_multi_product`, `is_board_approved`, `is_signed`, `is_invested`, `is_committed`, exposure columns (A09–A11), `risk_flag`, lifecycle day columns (A07), `reporting_date`, plus calendar and fiscal years (`approval_year`, `approval_fy`, … for approval, signing, investment, disclosure; IFC FY = Jul–Jun, labelled by the June year).
3. **Carry our flags** into `certified_investment_portfolio`:
   - every `flag_*` from `validated_projects`;
   - monitoring flags prefixed `mon_` (e.g. `mon_flag_review_overdue`, `mon_flag_over_disbursed`);
   - combined roll-ups: `needs_review` (project OR monitoring), `dq_max_severity` (worst of both), `review_owners` (union), `dq_messages` (concatenated);
   - `text_attributes_need_review` as his;
   - **drop** his `dq_*` columns.
4. Port `gold_client_scorecard` → `certified_client_scorecard`, with band thresholds and weights read from config. Add `n_review_overdue_active` and `n_high_severity_flags` per client.
5. Column comments: port his dictionary; rename keys to `amt_*`; add comments for every `flag_*`, `mon_flag_*` and roll-up column (take the text from the contract's `description`). Tags: `layer` = `raw|validated|enriched|certified`.

**Accept:** `certified_investment_portfolio` has 5,000 rows; `count_if(mon_flag_review_overdue)` = 324; `count_if(flag_board_date_passed)` = 237; the his-vs-merged sanity view (his §8) shows Closed 1302 / Active 1233 / Pending 1233 / Dropped 1232.

## Phase 6: Portfolio checks (`01_data/06_dq_checks.py`)

Port his CHECKS framework into `ops_dq_checks`, made **data-driven**:
- **B01–B08:**
  - Row count: `raw_*_current` rows = validated + quarantined.
  - Dollar control totals: sum of `try_cast` over `raw_projects_current` (all rows) must equal validated + quarantined sums within $0.05M.
  - No hard-coded 5,000 / 742,558.66 etc. Keep his figures only as an `info` check comparing to the first delivery.
- **K01–K06, S01–S05, V01–V05:** keep as portfolio-level assertions on the merged tables. Many duplicate contract rules; keep them anyway as an independent second check. Blocking ones stop the job.
- **D01–D06, T01–T03:** info, referencing the new flag columns.

**Accept:** all blocking checks pass on the real files; feeding `test_files/` triggers the expected stops at Stage 1/2/3, not here.

## Phase 7: Answers (WS1–WS3)

1. **WS1:** rename tables and columns; Q28 uses `abs(alloc_gap_musd) > 1`. For Q1, Q2, Q5, Q9, Q10, Q11, Q17, Q20, pass `sensitivity_sql` (same query plus `AND status <> 'Dropped'`) with `sensitivity_label = 'Excluding Dropped'`. Every `answer()` call lists its `assumption_ids`. Keep the Q27/Q30 charts.
2. Add a **reconciliation cell** to WS1:
   - regional totals sum to the portfolio total;
   - product split sums equal the product columns;
   - status percentages sum to 100 per region (Q23);
   - print OK/FAIL.
3. **WS2/WS3:** rename only. Keep his independent reconciliation. Re-verify his published figures:
   - WS2: 95 projects, $15,473M approved, $11,448M disbursed, $3,312M ECL;
   - WS3: picks Rosar Telecom Holdings, Zansorzen Renewables, Wenhargal Renewables, Bricor Finance Group.

   Any change is reported to the user, not silently accepted.
4. Optional WS3 enrichment: mention each pick's `n_review_overdue_active` in its evidence.

**Accept:** `answers_register` holds the 30 WS1 questions (+ details), each with SQL, assumptions and (where applicable) the sensitivity figure; WS2/WS3 figures unchanged.

## Phase 8: Agent, trust layer, Genie, evaluation

1. **`02_agent_capabilities.py`:**
   - Rename tables/columns in all 7 UC functions.
   - `data_quality_summary()` reads `ops_dq_checks` + `ops_dq_run_summary`.
   - Add an 8th function **`get_project_flags(project STRING)`**: flags, severity, owners and messages for one project (`project_url` or name).
   - Genie instructions: rename; add "include `needs_review`/`dq_max_severity` counts when aggregating amounts", "use `mon_flag_review_overdue` for overdue reviews", and the A03 sensitivity rule.
   - Genie data list: `certified_investment_portfolio`, `certified_client_scorecard`, `ref_assumptions`, `ops_dq_issues`.
   - Update grants.
2. **`cfo_agent.py`:** rename. Add `get_project_flags` to `TOOLS`/`SQL_TOOLS`.
3. **Deterministic caveat check (our idea, missing in his).** After Genie returns SQL, the trust layer computes how many `certified_investment_portfolio` rows in scope carry flags:
   - parse the SQL with `sqlglot` (Databricks dialect);
   - if it reads only `certified_investment_portfolio`, run `SELECT count(*), count_if(needs_review), count_if(dq_max_severity = 'high'), count_if(text_attributes_need_review) FROM certified_investment_portfolio WHERE <Genie's WHERE clause>`;
   - attach "N of M projects in this answer have open data-quality issues (K high)" to the footer;
   - if the SQL can't be analyzed (joins, CTEs, subqueries), say so and keep REVIEW_RECOMMENDED;
   - any high-severity hit makes the status at least REVIEW_RECOMMENDED;
   - add `sqlglot` to `requirements.txt` and the agent's pip install.

   Apply the same check to `answer()` in WS1 and store the counts in `answers_register` (`rows_in_scope`, `rows_needing_review`, `rows_high_severity`).
4. **Trust level naming:** keep his three statuses, map them to the colors the user knows: VALIDATED = Green, REVIEW_RECOMMENDED = Amber, HUMAN_REVIEW_REQUIRED = Red. Reasons are always listed.
5. **New `02_agent/04_evaluate_genie.py`: paraphrase consistency** (the "same question 150 ways" demo):
   - For each WS1 question, store 4 paraphrases in a table `genie_paraphrases` (question_id, paraphrase_no, text). Claude Code drafts them; the user reviews them.
   - Ask Genie each one via the Conversation API (`w.genie.start_conversation_and_wait`), re-run its SQL, and compare the main figure(s) with the certified answer in `answers_register` (relative tolerance 0.5%; same row count for list questions).
   - Write `genie_eval_results` and report **accuracy** (matches ground truth) and **consistency** (all phrasings agree) per question and overall.
   - Log to MLflow.
   - Throttle calls (Genie API rate limits); allow running a subset.
6. **`03_build_agent.py`:** rename; add one demo question about overdue reviews ("Which high-risk Active projects are overdue for review?") and one about data issues for a project.

**Accept:** functions compile; the agent answers the demo set with correct figures; the footer shows the flag counts; the evaluation notebook produces scores for at least 5 questions.

## Phase 9: App

1. Rename in `04_app.py`.
2. **Trust & quality tab:** add
   - the `ops_schema_gate_log` (latest holds),
   - `ops_raw_load_log`,
   - `ops_dq_run_summary` (flag counts vs profiling),
   - a "Needs review by owner" table from `ops_dq_issues`,
   - the Genie evaluation scores.
3. **Board / client tabs:** show `needs_review` badges on project rows.
4. `app.yaml`: unchanged except it must point at `ifc_challenge`/`portfolio`.

**Accept:** a business user can do the whole demo in the app.

## Phase 10: Packaging and orchestration

1. **`databricks.yml` (Asset Bundle):**
   - workspace root `/Workspace/Teams/ifc-cfo-copilot` (or per-user in dev target).
   - Job **`ifc_data_pipeline`**: tasks `00_config` → `00_reference` → `01_schema_gate` → `02_load_raw` → `03_validate` → `04_enrich` → `05_certify` → `06_dq_checks`, serverless, email on failure (user's address as a variable).
   - Job **`ifc_answers`**: `ws1` → `ws2` → `ws3`.
   - The app resource (`03_demo/04_app.py`).
   - Exclude `reference/` and `tests/` from sync.
2. **Behavior on no new files:** if Stage 1 finds nothing in `incoming/` and Stage 2 finds nothing in `accepted/`, stages 3–6 still rebuild from `raw_*_current`. That is fine and idempotent.
3. **README:** merge his README with ours:
   - layer names;
   - the 10 data findings plus ours: review overdue (70% of high-risk Active overdue; median days rise with risk), 237 Board-date-passed, under/over split, the status-filter sensitivity;
   - schema gate and contracts;
   - how to release a held file;
   - how to change a threshold (edit config, rerun).

   Update `WALKTHROUGH.md` and `IMPLEMENTATION_STRATEGY.md` the same way (remove bronze/silver/gold wording; keep his value case, failure modes and video script; add the schema-gate demo to the failure-mode table and the video).
4. **Manual steps the user must do** (list them in README §3):
   - re-add tables to the Genie space and paste the new instructions;
   - set `sql_warehouse_id` and `genie_space_id` in config;
   - re-run grants for the app's service principal;
   - redeploy the agent endpoint.

**Accept:**
- `databricks bundle validate` passes;
- `databricks bundle deploy` + `databricks bundle run ifc_data_pipeline` succeeds end to end;
- a re-run with `test_files/` dropped into `incoming/` holds them and leaves the certified tables unchanged.

---

## Things to verify on Databricks (cannot be tested locally)
- Spark multi-line CSV read gives exactly 5,000 rows (row-count reconciliation will stop it if not).
- `TRY_CAST`, `RLIKE` and `CONCAT_WS` behave as in the SQLite test.
- Working directory / config path resolution for bundled notebooks.
- `ai_query` on the chosen endpoint (5-row test first).
- `DECLARE OR REPLACE VARIABLE` support (serverless / DBR 14.1+); fallback is hard-coding the config value into the SQL text.
- Genie Conversation API rate limits during the paraphrase evaluation.
- Free/trial workspace limits: Apps, Model Serving, `agents.deploy`.

## Ground rules for whoever builds this
- Small steps; the user validates each phase on Databricks before the next.
- Never drop or overwrite `ref_text_feature_overrides`, `enriched_llm_extractions`, `answers_register`, `agent_audit_log` or the `raw_*` tables without asking.
- No full LLM extraction without explicit approval.
- Keep Python 3.11-compatible.
- Keep `CLAUDE.md` updated when a decision changes.
