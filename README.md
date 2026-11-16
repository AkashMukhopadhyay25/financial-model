# Cloudstruck: portfolio intelligence for IFC's CFO Office

**Team:** _<team name>_ · _<team members>_ · Accenture / BTA "Forward Deployed: Agentic Innovation Challenge", 2026

This README is the **handover document**: what the solution does, where every deliverable is, and how a client team
deploys, operates and maintains it without further support.

---

## 1. The solution in one minute

**The problem.** The CFO Office answers Board questions by hand from two separately held record sets (projects and
monitoring). An exposure summary takes about three weeks, follow-up questions cannot be answered in the meeting, and two
departments recently showed the Board **different figures for the same measure**.

**What we built on Databricks:**

| Layer | What it does |
|---|---|
| **Governed data** | Contract-checked pipelines take the two monthly CSVs through `raw_*` → `validated_*` → `enriched_*` → `certified_*` tables in Unity Catalog. Every problem row is kept and flagged with a severity and an owner, never silently dropped. 72 data-quality checks reconcile every layer. |
| **One set of definitions** | 24 written assumptions (`ref_assumptions`, A01–A24) are applied everywhere: certified answers, Genie, the agents and the app. The same question always gives the same figure. |
| **Genie** | Answers "what happened?" in plain language on the certified tables. The app adds a trust check that code computes, not Genie: Green / Amber / Red, plus the number of flagged projects in scope. |
| **Our own agents**, alongside Genie | **Reserve & Stress-Test Agent** ("what if credit worsens?") and **Capital Allocation Agent** ("where should new money go?"). The model chooses the analysis and explains it. Deterministic SQL computes every figure, and the app checks that each figure in the answer comes from that SQL. |
| **The app (Cloudstruck)** | A Databricks App for analysts, executives and the Credit Risk Committee: Overview, Portfolio analytics, Risk & exposure, Client intelligence (with both agents), Early warning, Monthly review and Board briefing. Every page shows its SQL, and any project opens to its full record. |
| **Human in the loop** | Agents' answers, clients and projects can be sent to the Credit Risk Committee. The Board briefing has a review queue where a reviewer records a decision. Everything is logged. |

**Results on the first delivery (reporting date 30 June 2026):**
- **WS1:** 30 portfolio questions answered (36 certified answers with detail lists), each with SQL, assumptions and a
  data-quality count; 14 reconciliation checks pass.
- **WS2:**
  - 95 Category A projects are Past Due or on the Watchlist, across 61 clients: $15,473.36M approved, $11,447.52M
    disbursed;
  - recommended provision **$3,311.72M** (60% of Past Due disbursed);
  - for comparison, ECL on the whole portfolio is $7,596.21M.
- **WS3:** continue with **Rosar Telecom Holdings** and **Zansorzen Renewables**; reduce or review **Wenhargal
  Renewables** and **Bricor Finance**. Exposure affected is $5,974M and $7,782M. Condition: all four sit mainly in
  Sub-Saharan Africa, which is above the 25% concentration limit. See `04_answers/ws3/board_recommendation.md`.
- **Consistency:** 24 of 24 paraphrased questions to our agents returned the identical figure
  (`02_agent/agent_evaluation_report.md`).

**Who it is for:** CFO Office analysts, the CFO, Board directors, the Credit Risk Committee and the data owners.
Their workflows before and after are in `docs/requirements_and_success.md`.

**Success criteria, measured:**

| Criterion | Target | Result |
|---|---|---|
| Time to answer | minutes, not weeks | certified answer ~1 s; Board briefing ~1 s; stress-test agent 4.9 s; capital-allocation agent 11 s |
| Same figure however asked | 100% | 24 of 24 agent phrasings |
| Every agent figure traced to SQL | 100% | enforced by code; untraced figures turn the answer Amber |
| Reconciliation | 0 unexplained differences | 72 of 72 data checks; 14 of 14 WS1 checks |
| Coverage | WS1–WS3 | 30 of 30 questions, 2 of 2 Board questions, four-client recommendation, both optional extensions |

**Value, with stated assumptions** (`docs/business_case.md`): about **450 analyst-days a year** freed from building Board
and monthly packs and from answering recurring questions. That is about two analysts, or **USD 360,000 a year** at an
assumed USD 800 per day. Directors' follow-up questions are answered in the meeting, and one definition per measure
ends conflicting figures. The same document has the adoption plan.

## 2. Where each deliverable is

| Brief item | Location |
|---|---|
| README (handover) | this file |
| Configuration | `config/pipeline_config.yml` (every name, threshold, model and ID), `00_setup/00_config` |
| Data pipelines: load, validate, combine | `01_data/01_schema_gate` → `02_load_raw` → `03_validate` → `04_enrich` → `05_certify` → `06_dq_checks` → `07_client_views`; reference data `01_data/00_reference`; monthly history `07_snapshot_month`, `08_trends`, `run_monthly_pipeline` |
| Data contracts | `contracts/projects_contract.yml`, `contracts/monitoring_contract.yml` |
| Agent capabilities (tools) | `app/backend/stress.py` (stress engine), `app/backend/allocation.py` (A23 ranking, A24 research), `config/market_outlook.yml` (cited sources) |
| Agent build | `app/backend/agent_core.py` (shared core), `stress_agent.py`, `allocation_agent.py`. The agents run inside the Databricks App, which calls the Foundation Model API. |
| Agent evaluation | Job `cloudstruck_agent_evaluation` (`02_agent/run_agent_evaluation.py` → `app/backend/evaluate.py`): results to `ops_agent_evaluation`, `02_agent/agent_evaluation_report.md` and an MLflow run; Genie test sheet `02_agent/genie_phrasing_test.md` |
| Agent traces (MLflow) | Experiment `/Shared/cloudstruck_agents`: one trace per agent run (question → model calls → tool calls with SQL → answer, trust level), from the app and the evaluation job |
| Orchestration | Job `cloudstruck_full_pipeline` (11 tasks, failure email, monthly schedule paused); `databricks.yml` (Asset Bundle: both jobs + the app, validated) |
| Demo (business user's view) | the Databricks App `ifc-cfo-intelligence` (`app/`); walkthrough and video script `03_demo/README.md` |
| WS1 answers + SQL | `04_answers/ws1/ws1_answers` → `answers_register` (workstream WS1) |
| WS2 answers + SQL | `04_answers/ws2/ws2_board_questions` → `answers_register` (WS2) |
| WS3 recommendation | `04_answers/ws3/board_recommendation.md` (Board-ready), notebook `04_answers/ws3/ws3_client_recommendations` → `ws3_recommendations` |
| Architecture diagram | `assets/architecture_diagram_agentic_solution.png` (Mermaid source `.mmd` next to it) |
| Users, requirements, success criteria | `docs/requirements_and_success.md` |
| Value case and adoption plan | `docs/business_case.md` |
| Request trace, failure scenarios, tradeoffs, pilot to scale | `docs/architecture_defense.md` |

In the Databricks workspace the code is at `/Workspace/Users/pruthvi.doshi@rotman.utoronto.ca/financial-model`, and the
data is in catalog `workspace`, schema `portfolio`.

## 3. Architecture

![Architecture](assets/architecture_diagram_agentic_solution.png)

| Component | Responsibility | Why this design |
|---|---|---|
| **Data contracts + schema gate** | Reject a file whose columns changed before anything is read; the job fails on purpose so someone is alerted | The monitoring team and the portfolio team deliver separately; drift must stop the pipeline, not corrupt the Board figures |
| **Validate (quarantine vs flag)** | Unusable rows are quarantined; questionable rows are kept with a flag, severity and owner | Excluding questionable rows would change the totals silently. Flagging keeps the figures complete and the doubts visible. The run stops if more than 5% would be quarantined. |
| **Enrich** | Text attributes from project descriptions: renewable generation, MW, small-business finance, product. Rules + `ai_query` LLM + reviewer overrides | The [Challenge] questions need meaning from free text. The two methods are compared, and disagreements go to a person. |
| **Certified tables** | One row per project, joined to monitoring on `project_url`; every column commented for Genie | Project Number is not unique: joining on it inflates monitoring from 3,768 to 6,477 rows |
| **`ref_assumptions` (A01–A24)** | Every business definition, written once | The brief: "state the assumptions and apply them consistently". Genie, the agents, the app and the notebooks all read the same rows. |
| **Genie space** | Plain-language analytics on the certified tables | Fastest way for analysts to ask new questions; the app adds the trust check |
| **Shared agent core** | Tool loop, prefetched context, figure tracing, consistency checks, audit log (`ops_agent_runs`) | One place for the guardrails; a new agent is a prompt plus tools |
| **Stress-Test and Capital Allocation agents** | Scenario analysis and allocation advice with cited research | WS3 asks for an agent of our own. Two narrow agents choose tools more reliably than one broad agent, and each is tested separately. |
| **Deterministic engines** (`stress.py`, `allocation.py`) | Compute every figure the agents use | The model never does arithmetic, so the same scenario gives the same number however it is asked |
| **Foundation Model API** (`databricks-qwen3-next-80b-a3b-instruct`) | Language model behind the agents | Open-weight and hosted in the workspace, so no data leaves Databricks. Chosen after testing three models on the same questions: fastest (~5–12 s), and every figure traced. Swap in the config. |
| **Databricks App** (FastAPI + React) | The product business users open | Runs as a service principal with least privilege, reads through the SQL warehouse, and caches page views for 10 minutes |

## 4. Data quality and business definitions

- **Three money measures, never mixed:**
  - **Approved** = the Board figure, used for totals;
  - **Allocated** = the four product columns, used for product mix only;
  - **Disbursed** = from monitoring.
- **Flags on the first delivery** (0 rows quarantined): outdated record 607, review overdue 324, Board date passed 237,
  over-allocated 78 (high), under-allocated 72, region restated 43, signed before approval 37, missing description 31,
  and others.
  - 1,260 projects carry a flag (78 high severity). They stay in every figure, and each answer reports how many of
    its projects are flagged.
  - The issues are routed to four owners in `ops_dq_issues`.
- **Assumptions the reader should know:**
  - A03: a question that names no status includes all statuses, Dropped included. The excluding-Dropped figure is
    stored next to it.
  - A09–A11: current exposure = Active disbursed; ECL = 60% of Past Due disbursed.
  - A15: client bands.
  - A18: review overdue, tiered by risk rating.
  - A22: early-warning signals.
  - A23–A24: capital-allocation ranking and external research.
  - The full list is in `ref_assumptions` and the app's "Assumptions" drawer.
- **Trust levels:** Green (validated), Amber (review recommended), Red (human review required), always with reasons.
  There is no numeric confidence score.

## 5. Deploy (a client team, from scratch)

Prerequisites: a Databricks workspace with Unity Catalog, a serverless SQL warehouse, and Foundation Model API
pay-per-token endpoints.

1. **Code.** Import this repository into the workspace (Workspace → Create → Git folder), or upload it with the
   workspace import API.
2. **Settings.** Edit `config/pipeline_config.yml`:
   - `environment.catalog` and `schema`;
   - `serving.sql_warehouse_id`;
   - `serving.agents.*` model names.

   Nothing else hard-codes a name.
3. **Data.** Upload the two CSVs to the `landing` volume. For monthly runs, use `incoming/YYYY-MM/`.
4. **Pipeline.** Run the job **`cloudstruck_full_pipeline`**: Workflows → Jobs → cloudstruck_full_pipeline → Run now.
   It rebuilds every table, in the order below. A step's failure emails the owner; a changed column fails it on purpose.
   The same tasks are in `databricks.yml`, so `databricks bundle deploy -t prod` recreates the jobs and the app in a new
   workspace. The stages, for running by hand:
   1. `00_setup/00_config`
   2. `01_data/01_schema_gate`
   3. `02_load_raw`
   4. `03_validate`
   5. `00_reference`
   6. `04_enrich` (`run_llm_extraction: false` reuses cached extractions; set it to true only for new descriptions)
   7. `05_certify`
   8. `06_dq_checks`
   9. `07_client_views`

   Then run `04_answers/ws1`, `ws2` and `ws3`. The monthly path does all of this in one notebook:
   `01_data/run_monthly_pipeline`.
5. **Genie.** Create a Genie space on `certified_investment_portfolio`, `ref_assumptions` and `ops_dq_issues`, and
   add the certified SQL from `answers_register` as example queries. Put its ID in `serving.genie_space_id`.
6. **App.** Compute → Apps → Create app `ifc-cfo-intelligence`, with source code path `…/financial-model/app`. Add
   three resources:
   - SQL warehouse (`sql-warehouse`, Can use);
   - Genie space (`genie-space`, Can run);
   - serving endpoint `databricks-qwen3-next-80b-a3b-instruct` (`stress-agent-model`, Can query).

   Then grant the app's service principal access: `app/README.md` has the exact SQL.
7. **Check.** Open the app: the header shows the data date. Then run `PYTHONPATH=. python -m app.backend.evaluate`;
   it should report 24 of 24 consistent.

## 6. Operate

| Task | How |
|---|---|
| **Load a month** | Upload both files to `landing/incoming/YYYY-MM/` → run `01_data/run_monthly_pipeline`. A file whose columns changed is moved to `held/` and the job fails on purpose (check `ops_schema_gate_log`). |
| **Correct a month** | Upload the corrected file into the same month folder and rerun. The new upload becomes active, the old one stays in Raw marked superseded, and only that month is rebuilt. |
| **Work the data-quality list** | `ops_dq_issues` lists open issues by owner, and the app shows them on every page. Text-attribute decisions go into `ref_text_feature_overrides`. That table is never overwritten; it holds human decisions. |
| **Human review** | Items sent from the app appear in Board briefing → "Human review queue". "Mark reviewed" records the decision with the reviewer's name and time (`ops_review_requests`, append-only). |
| **Audit an agent answer** | `ops_agent_runs` holds every question, answer, tool call, SQL, trust level, model and latency. Reopen any run in the app with "Past runs". |
| **Monitor quality** | Run the job `cloudstruck_agent_evaluation` after any change to a prompt, tool or model. It fails if consistency drops below 100%, and logs an MLflow run with the metrics and report. Have a person rerun `02_agent/genie_phrasing_test.md` after changing the Genie space. |
| **Debug an agent answer** | Experiments → `/Shared/cloudstruck_agents` → Traces: every run, step by step (model calls, tool calls with their SQL, latency, trust level). |
| **Board pack** | Board briefing → "Print / save as PDF" or "Download (.md)". Every figure comes live from the certified tables. |

## 7. Maintain and extend

- **Change a threshold or definition:** edit `config/pipeline_config.yml` (the assumption text is generated from it),
  rerun `00_reference` and the affected stages. Bump the contract version if a rule changes.
- **Add a column from a new delivery:** add it to the contract (version and changelog), then rerun the schema gate. A
  file with an unannounced column is held, by design.
- **Add market research:** add a row to `config/market_outlook.yml` (publisher, title, date, URL, stance, finding) and
  rerun `00_reference`. Always check the source is the latest edition: the October 2025 WTO outlook was superseded in
  October 2026.
- **Swap the agents' model:** change `serving.agents.*` and `app/app.yaml`, update the app resource, then rerun the
  evaluation.
- **Add an agent:** write a `*_agent.py` with instructions, tools (deterministic functions returning rows plus SQL) and
  optional prefetch and consistency checks; add an API route and a panel. The core supplies figure tracing, trust
  level and audit.
- **Run the app locally:**

  ```bash
  uvicorn app.backend.main:app --reload
  ```

  With no warehouse configured, it builds a DuckDB preview from `data/`.

## 8. Limitations and the path from pilot to scale

The full version is in `docs/architecture_defense.md`: a phased pilot plan with exit criteria, failure scenarios, the
design alternatives we rejected, and how the solution scales.

- **The data is synthetic**, and expected credit loss uses the brief's simplified model (60% of Past Due disbursed).
  A production version would use IFC's own probability-of-default and loss-given-default models and recovery data.
- **No last-review date exists** in the monitoring data, so "review overdue" is derived (A18).
- **Market research is curated and paraphrased.** It is cited and dated but must be checked against the full reports;
  the next step is a scheduled job that flags sources older than 12 months.
- **Genie's paraphrase consistency is tested by a person** (team rule: sessions do not call the Genie API). Our agents
  are tested automatically.
- **The model's wording can be imprecise** (for example "low" for a mid-ranked rate). The figure check guarantees the
  numbers, not the adjectives.
- **Path to scale:**
  1. Unpause the monthly schedule of `cloudstruck_full_pipeline` once deliveries arrive in month folders. The job,
     failure alerts, Asset Bundle, MLflow traces and evaluation job are already in place.
  2. Move the app to SSO groups (analyst / committee roles).
  3. Add a Board-prep agent and a figure-reconciliation agent on the same core.
  4. Make the evaluation job a required gate in CI before any model or prompt change reaches the app.
  5. Deploy to new workspaces with the Asset Bundle (`databricks.yml`), one command per environment.

## 9. Repository map

```
config/          pipeline_config.yml (all settings) · market_outlook.yml (A24 sources) · monthly dev config
contracts/       data contracts for the two source files
00_setup/        config loader, shared helpers, monthly helpers, shared portfolio SQL
01_data/         pipeline notebooks (schema gate → certified, DQ checks, client views, monthly history, trends)
02_agent/        agent evaluation report · Genie phrasing test sheet
03_demo/         business-user walkthrough and 3-minute video script
docs/            requirements and success criteria · business case and adoption · architecture defense
04_answers/      ws1, ws2, ws3 (notebooks + Board memo)
app/             Databricks App: backend (FastAPI, agents, engines) · frontend (React; built files in frontend/dist)
assets/          architecture diagram
tests/           Stage 3 SQL run locally on SQLite
test_files/      broken files for the schema-gate demo · demo months
reference/       the teammate's original solution, kept read-only for traceability
cfo_copilot/     the teammate's earlier full solution (superseded by app/, kept for reference)
data/            source CSVs (not in Git)
```

Developer history and every decision taken: `CLAUDE.md`, `MERGE_PLAN.md`.
