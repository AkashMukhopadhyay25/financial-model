# Bellwether app

Bellwether is the CFO Office portfolio-intelligence app. A bellwether is the early indicator that shows where things are
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

WS2/WS3 back up the teammate's earlier rows (`answers_register_ws2_teammate_backup`, `answers_register_ws3_teammate_backup`,
`ws3_recommendations_teammate_backup`) the first time they run.

## 2. Create the Genie space (once)

1. Left sidebar → **Genie** → **New**.
2. **Data**: add `workspace.portfolio.certified_investment_portfolio`, `certified_client_scorecard`, `ref_assumptions`.
3. **Settings**: SQL warehouse = *Serverless Starter Warehouse*. Title: `IFC CFO Portfolio`.
4. **Instructions**: paste the business rules (count projects by `project_url`; totals use `total_approved_musd`; no status
   filter unless asked, A03; "last N years" anchored on `reporting_date`; North Africa = filter by country).
5. Copy the space ID from the URL (`.../genie/rooms/<space-id>`) into `serving.genie_space_id` in `config/pipeline_config.yml`.

## 3. Deploy the app

1. Pull the latest code into your Git folder (Workspace → Git folder → branch menu → **Pull**).
2. Left sidebar → **Compute** → **Apps** tab → **Create app** → **Create a custom app**. Name: `ifc-cfo-intelligence`.
3. **App resources** → **Add resource**:
   - **SQL warehouse**: Serverless Starter Warehouse, permission *Can use*, resource key **`sql-warehouse`**;
   - **Genie space**: the space from step 2, permission *Can run*, resource key **`genie-space`**.
4. Create the app, then **Deploy** → source code path = the `app` folder inside your Git folder
   (e.g. `/Workspace/Users/<you>/financial-model/app`).
5. Grant the app's service principal access to the data. Its name is on the app's **Authorization** tab. In a SQL editor:

```sql
GRANT USE CATALOG ON CATALOG workspace TO `<app-service-principal>`;
GRANT USE SCHEMA, SELECT ON SCHEMA workspace.portfolio TO `<app-service-principal>`;
GRANT MODIFY ON TABLE workspace.portfolio.ops_review_requests TO `<app-service-principal>`;
```

6. Open the app URL. The header shows "Genie space not configured" if the `genie-space` resource is missing.

## Local development (no Databricks)

```bash
pip install -r app/requirements.txt duckdb pandas pyyaml
```

```bash
uvicorn app.backend.main:app --port 8000
```

Run it from the repo root and open http://localhost:8000. The first start builds `app/.preview/preview.duckdb` from
`data/` by running the real pipeline stages 1–3 locally, the same scorecard/early-warning SQL (`00_setup/portfolio_sql.py`)
and the WS2/WS3 rules. Preview figures match the certified ones (WS2 and WS3 checked), but there are no text attributes or
certified WS1 SQL, and Genie is off. Delete `app/.preview/` to rebuild.

To change the frontend:

```bash
cd app/frontend && npm install && npm run dev
```

`npm run dev` serves on http://localhost:5173 and forwards `/api` to port 8000. Before committing, run `npm run build`
so `frontend/dist` is updated; the deployed app serves those built files.
