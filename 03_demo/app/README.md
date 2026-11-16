# Cloudstruck app

Cloudstruck is the CFO Office portfolio-intelligence app. A cloudstruck is the early indicator that shows where things are
heading, which is what the Early warning page does: it spots trouble before it becomes Past Due.

A Databricks App with six pages, built from the UI mockups:

| Page | Workstream | Reads |
|---|---|---|
| Overview | all | `certified_investment_portfolio`, `certified_early_warning`, `ops_*` logs |
| Portfolio analytics | WS1 | `certified_investment_portfolio` (filters, charts), `answers_register` (30-question library), **Genie** |
| Risk & exposure | WS2 | `certified_investment_portfolio` (same SQL as the certified WS2 answers), `answers_register` |
| Client intelligence | WS3 | `certified_client_scorecard`, `ws3_recommendations` |
| Early warning | early warning | `certified_early_warning`, **Genie** |
| Board briefing | all | everything above; download as Markdown or print to PDF |

**Every number on screen comes with the SQL that produced it** (Evidence / SQL buttons).

**Genie:** the app talks to an AI/BI **Genie space** through the Genie Conversation API. (Genie Code, the assistant
inside notebooks, has no API that apps can call.) For each answer the app shows:
- Genie's text, result table/chart and SQL;
- a **data-quality caveat that the app computes itself**: it runs Genie's WHERE clause on `certified_investment_portfolio`
  and counts the flagged projects in scope (`backend/trust.py`). Trust levels: Green = Validated, Amber = Review
  recommended, Red = Human review required;
- the matching **certified answer** when the question is one of the 30 WS1 questions.

"Flag for review" and "Mark reviewed" append to `ops_review_requests` with the signed-in user's email.

## Code layout

```
app/
  app.yaml              Databricks App definition (command, env, resource keys)
  requirements.txt      Python packages installed by Databricks Apps
  backend/              FastAPI: main.py (routes), queries.py (all SQL), genie.py, trust.py, sql.py, settings.py
                        local_preview.py builds a DuckDB copy from data/ for local development only
  frontend/             React (Vite). src/ = source; dist/ = built files, committed, served by FastAPI
```

## 1. Build the tables the app reads (Databricks, once per data refresh)

Run in this order (Workspace → your Git folder → open the notebook → **Run all**):

1. `01_data/00_reference` (adds assumption A22, early-warning signals)
2. `01_data/07_client_views` (new): `certified_client_scorecard`, `certified_early_warning`, `ops_review_requests`
3. `04_answers/ws2/ws2_board_questions` (expected: 95 projects, $15,473.36M approved, $11,447.52M disbursed, $3,311.72M ECL)
4. `04_answers/ws3/ws3_client_recommendations` (expected picks: Rosar Telecom Holdings, Zansorzen Renewables Corp; Bricor Finance Group, Wenhargal Renewables Corp)


## 2. Create the Genie space (once)

1. Left sidebar → **Genie** → **New**.
2. **Data**: add `workspace.portfolio.certified_investment_portfolio`, `certified_client_scorecard`, `ref_assumptions`.
3. **Settings**: SQL warehouse = *Serverless Starter Warehouse*. Title: `IFC CFO Portfolio`.
4. **Instructions**: paste the business rules (count projects by `project_url`; totals use `total_approved_musd`; no status
   filter unless asked, A03; "last N years" anchored on `reporting_date`; North Africa = filter by country).
5. Copy the space ID from the URL (`.../genie/rooms/<space-id>`) into `serving.genie_space_id` in `00_setup/config/pipeline_config.yml`.

## 3. Deploy the app

1. Pull the latest code into your Git folder (Workspace → Git folder → branch menu → **Pull**).
2. Left sidebar → **Compute** → **Apps** tab → **Create app** → **Create a custom app**. Name: `ifc-cfo-intelligence`.
3. **App resources** → **Add resource**:
   - **SQL warehouse**: Serverless Starter Warehouse, permission *Can use*, resource key **`sql-warehouse`**;
   - **Genie space**: the space from step 2, permission *Can run*, resource key **`genie-space`**;
   - **Serving endpoint**: `databricks-qwen3-next-80b-a3b-instruct`, permission *Can query*, resource key
     **`stress-agent-model`** (the Reserve & Stress-Test Agent's model; must match `IFC_STRESS_AGENT_MODEL` in `app.yaml`).
4. Create the app, then **Deploy** → source code path = the `app` folder inside your Git folder
   (e.g. `/Workspace/Users/<you>/financial-model/app`).
5. Grant the app's service principal access to the data. Its name is on the app's **Authorization** tab. In a SQL editor:

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<app-service-principal>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.portfolio TO `<app-service-principal>`;
GRANT MODIFY ON TABLE workspace.portfolio.ops_review_requests TO `<app-service-principal>`;
-- the app creates and appends ops_genie_history and ops_agent_runs (agent audit trail):
GRANT CREATE TABLE, MODIFY ON SCHEMA workspace.portfolio TO `<app-service-principal>`;
```

6. Open the app URL. The header shows "Genie space not configured" if the `genie-space` resource is missing.

## Local development (no Databricks)

```bash
pip install -r 03_demo/app/requirements.txt duckdb pandas pyyaml
```

```bash
uvicorn app.backend.main:app --port 8000 --app-dir 03_demo
```

Run it from the repo root and open http://localhost:8000. The first start builds `03_demo/app/.preview/preview.duckdb` from
`data/` by running the real pipeline stages 1–3 locally, the same scorecard/early-warning SQL (`00_setup/portfolio_sql.py`)
and the WS2/WS3 rules. Preview figures match the certified ones (WS2 and WS3 checked), but there are no text attributes or
certified WS1 SQL, and Genie is off. Delete `03_demo/app/.preview/` to rebuild.

To change the frontend:

```bash
cd 03_demo/app/frontend && npm install && npm run dev
```

`npm run dev` serves on http://localhost:5173 and forwards `/api` to port 8000. Before committing, run `npm run build`
so `frontend/dist` is updated; the deployed app serves those built files.

## Reserve & Stress-Test Agent (Client intelligence → Stress-test agent)

The team's own agent alongside Genie (WS3). Genie answers "what happened?"; this agent answers "what if?".

- **How it works.** The user asks a what-if in plain language. The model (a Databricks-hosted open-weight model,
  `serving.agents.stress_test_model` in the config / `IFC_STRESS_AGENT_MODEL` in `app.yaml`) turns it into scenario
  parameters and calls governed tools. The tools are deterministic SQL on `certified_investment_portfolio` and
  `ref_assumptions` (`backend/stress.py`):
  - `run_stress_scenario`: baseline vs stressed expected credit loss. Projects that move to default: Watchlist
    migration and/or rating ≥ N, within region, country (incl. "North Africa"), industry, client or E&S category
    filters. Loss rate defaults to A11's 60%; an optional drawdown share of undisbursed commitments can be set.
    Returns a summary, a breakdown and the 10 largest contributors.
  - `get_risk_baseline`: where exposure, Past Due, Watchlist and ECL sit today.
  - `get_assumptions`: A09–A11 and the other governed definitions.
- **Guardrails** (`backend/agent_core.py`, shared by every agent we add):
  - the model never computes a figure;
  - after it answers, the app checks every figure against the tool results, and any figure it cannot trace is listed
    and the answer is marked Amber;
  - trust level Green / Amber / Red with reasons, plus data-quality counts for the shocked projects;
  - every run is logged to `ops_agent_runs` (question, answer, tools, SQL, trust level, model, latency);
  - "Send to Credit Risk Committee" files the result in `ops_review_requests`.
- **API.** `GET /api/agents/stress-test` (model, presets, tools), `POST /api/agents/stress-test/ask`
  `{question, history}`, `GET /api/agents/stress-test/runs`, `GET /api/agents/runs/{run_id}`.
- **Model choice (2026-11-16)**, on the same three questions:
  - qwen3-next-80b: about 5 s, every figure traced;
  - gpt-oss-120b: close behind;
  - llama-3.3-70b: 15–18 s, added a filter nobody asked for; the figure check caught its errors.

  To swap the model, change the config, `app.yaml` and the app resource.
- **Reconciles with WS2.** The baseline ECL is $7,596.21M. "Every Watchlist project defaults" adds $10,109.45M
  (60% × $16,849.08M Watchlist disbursed). In "rated 5–6 default", Bricor Finance and Wenhargal Renewables, the two
  WS3 reduce / review picks, are the top drivers.

## Capital Allocation Agent (Client intelligence → Capital allocation agent)

The second of our own agents, on the same core (`agent_core.py`). It answers: where should IFC put new commitments,
where should it be careful, and does that change the four-client recommendation? It covers the WS3 optional extension
"External research".

- **Two views, kept separate:**
  - **Our track record (A23):** `allocation.rank_segments` ranks industries, regions and industry × region on four
    credit metrics from `certified_investment_portfolio`:
    - distressed share of exposure;
    - ECL / exposure;
    - share of closed disbursed exited at a loss;
    - exposure-weighted risk rating.

    Rank 1 is best and the overall rank is the average of the four. A region above 25% of current exposure is flagged
    as concentrated.
  - **The market (A24):** `ref_market_outlook`, built from `00_setup/config/market_outlook.yml`. It holds eight curated sources
    (IMF, World Bank, IEA, GSMA, WTO, FAO), each with publisher, title, date, URL and stance. There is no live web
    access: every market claim is cited [S#] and dated.
- **The decision rule is code, not the model:** `allocation_summary`.
  - Prioritise the best-ranked industry and be cautious on the last.
  - Grow in the best-ranked regions that are not concentrated; limit new exposure in concentrated or last-ranked regions.
  - The model explains this result and checks the four-client recommendation, using each client's industry and region
    ranks and flags, which code attaches.
- **Context fetched before the model runs:** the summary, both rankings, the outlook and the four clients. The model
  cannot skip them.
- **Consistency check (deterministic):** the answer turns Amber if it prioritises a concentrated region or skips the
  four-client check. The figure check also reads "USD 240 billion" style figures.
- **Result on the first delivery (2026-11-16):**
  - prioritise **Energy** (1st of 5; the IEA agrees, [S3]), growing in South Asia and East Asia & Pacific;
  - caution on **Finance** (5th of 5; the World Bank and IMF agree, [S8]);
  - limit new exposure in **Sub-Saharan Africa**, which is concentrated (27.8% > 25%) and ranks 6th of 6.

  All four WS3 clients are in Sub-Saharan Africa. The two CONTINUE picks hold on the condition that the region's share
  does not increase; the two REDUCE_OR_REVIEW picks are reinforced.
- **API:** `GET /api/agents/capital-allocation`, `POST /api/agents/capital-allocation/ask`,
  `GET /api/agents/capital-allocation/runs`.
- **Pipeline:** `01_data/00_reference` builds A23, A24 and `ref_market_outlook`. On 2026-11-16 they were loaded directly
  with the same code. To add research, edit `00_setup/config/market_outlook.yml` and rerun `00_reference`.

