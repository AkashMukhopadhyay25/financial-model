# `monthly/`: the monthly history pipeline

This folder powers the app's **Monthly review** page: what changed from one month to the next (clients that
deteriorated or improved, new business, KPI trends). It runs on the demo months **June–October 2026**, in its own schema
**`workspace.portfolio_monthly_dev`**, so the main certified tables in `workspace.portfolio` are never touched.

It is a self-contained copy of the pipeline set up for monthly deliveries. The main pipeline, used for WS1–WS3, is in
the parent folder `/Workspace/Shared/Cloudstruck`.

## How it runs

1. Each month's two files (projects and monitoring) are placed in a month folder in the landing volume:
   `landing/incoming/YYYY-MM/`. The app's **Load a new month** button does this for you.
2. The job **`run_monthly_pipeline`** (Jobs & Pipelines) runs `01_data/run_monthly_pipeline` with
   `config/pipeline_config_monthly_dev.yml`. It:
   - checks each new file's columns against the contract (schema gate);
   - loads it to Raw;
   - for every month that changed, oldest first: validates it, rebuilds the reference data, enrichment and the
     certified table, runs the data-quality checks, and saves a snapshot of that month;
   - finally recomputes the trends.
3. A corrected file for a month that was already loaded replaces it. The earlier upload is kept in Raw, marked
   superseded, and only that month is rebuilt.

## What each folder contains

| Folder / file | What it contains | Used by the job? |
|---|---|---|
| `01_data/` | The pipeline notebooks. **`run_monthly_pipeline`** is the one the job runs; it calls the others in order: `01_schema_gate` (column check), `02_load_raw` (load to Raw, history kept), `03_validate` (types, quarantine, data-quality flags), `00_reference` (assumptions and reference tables), `04_enrich` (text attributes from descriptions), `05_certify` (one row per project), `06_dq_checks` (reconciliation and checks), `07_snapshot_month` (saves the month into `certified_investment_portfolio_history`), `08_trends` (month-on-month KPIs and project changes) | Yes |
| `00_setup/` | Shared setup every notebook loads: `00_config` (reads the settings, creates the schema and landing folders), `ifc_common.py` (helpers: config, table names, contracts), `ifc_monthly.py` (month folders, which upload is active for each month, which months need rebuilding) | Yes |
| `config/` | `pipeline_config_monthly_dev.yml`: the monthly settings (schema `portfolio_monthly_dev`, KPIs and thresholds for trends); it extends `pipeline_config.yml`, the shared settings | Yes |
| `contracts/` | The data contracts for the two source files: expected columns, validation rules, flags and their owners | Yes |
| `test_files/demo_months/` | The demo deliveries, one folder per month (2026-06 to 2026-10). October also has a corrected monitoring file, to show how a correction replaces a month. | Source of the demo data |
| `test_files/make_demo_months` | The notebook that generated the demo months and puts them in the landing folder | Only to recreate the demo |
| `test_files/*.csv` | Deliberately broken files (added, dropped or renamed column, empty, header only, broken quotes, reordered columns) to show that the schema gate stops bad deliveries | No; for demonstrating the gate |
| `04_answers/ws1/` | A copy of the WS1 answers notebook that came with this folder; the real one is in the parent folder | No |
| `tests/` | A developer check that runs the validation SQL locally on SQLite | No |

## Where the results go

Schema `workspace.portfolio_monthly_dev`:
- `certified_investment_portfolio_history`: one snapshot per month;
- `kpi_monthly`, `kpi_month_over_month`, `kpi_latest_scorecard`: the trends;
- `project_month_changes`: every project-level change between months;
- `ops_monthly_loads`, `ops_monthly_snapshots`: which upload is active for each month, and when each month was
  snapshotted.

The app's Monthly review page reads these tables.
