# Demo months: synthetic monthly deliveries (June to October 2026)

**These files are synthetic demo data.** IFC gave us one real delivery (as of 2026-06-30). To show month-on-month
history, trends and a same-month correction, `test_files/make_demo_months.py` generated four follow-on months from
it. In production each month would be IFC's own delivery, uploaded the same way.

## Files

| Folder | Files | Rows (projects / monitoring) | Notes |
|---|---|---|---|
| `2026-06/` | `synthetic_ifc_projects_5000.csv`, `synthetic_project_monitoring_2026-06.csv` | 5,000 / 3,768 | The original delivery, unchanged |
| `2026-07/` | `…_2026-07.csv` | 5,011 / about 3,780 | Stress begins |
| `2026-08/` | `…_2026-08.csv` | 5,020 / 3,788 | Stress peaks |
| `2026-09/` | `…_2026-09.csv` | 5,032 / 3,800 | Review drive |
| `2026-10/` | `…_2026-10.csv`, `synthetic_project_monitoring_2026-10.csv`, `synthetic_project_monitoring_2026-10_corrected.csv` | 5,049 / 3,817 | Recovery; first monitoring file has a planted keying error, `_corrected` fixes it |

The folder name is the reporting month. File names match the data contracts (`synthetic_ifc_projects_*.csv`,
`synthetic_project_monitoring*.csv`), so the files can be uploaded as they are.

## How the months were generated

`make_demo_months.py` starts from the June delivery and changes each month a little, with a fixed random seed per
month (the files are reproducible):

- **Disbursements:** about 30% of Active projects draw down part of their undisbursed amount (never above approved).
- **Lifecycle:** Pending projects get Board approval, sign, become Active with a first disbursement; a few long-running
  Active projects close.
- **New projects:** 8 to 20 new Pending projects a month, for existing clients.
- **Credit risk:** Performing → Watchlist → Past Due moves, recoveries, and the rating changes that go with them.
- **Reviews:** each open project is either reviewed (days since review reset) or a month older.

The story built in, so the trends have something to show:

| Month | What happens | Past Due | Watchlist | Reviews overdue |
|---|---|---|---|---|
| Jun | Original delivery | 91 | 164 | 324 |
| Jul | Stress in Energy and Sub-Saharan Africa | 100 | 182 | 396 |
| Aug | Stress continues, few reviews | 108 | 199 | 481 |
| Sep | Review drive on high-risk projects | 110 | 181 | 265 |
| Oct | Recovery and growth | 104 | 134 | 188 |

**Correction test:** `synthetic_project_monitoring_2026-10.csv` wrongly marks 25 performing Energy projects as Past
Due (October showed 129 Past Due). Uploading `synthetic_project_monitoring_2026-10_corrected.csv` for 2026-10
replaces only October (Past Due 129 → 104). The earlier upload stays in Raw, marked inactive in `ops_monthly_loads`.

Every month keeps the contract rules (Dropped = not monitored, Pending = no disbursement, disbursed ≤ approved,
client IDs and names unchanged), so all blocking data-quality checks pass.

## Where it runs (workspace dbc-ba139e62-9140)

| What | Where |
|---|---|
| Schema | `workspace.portfolio_monthly_dev` (separate from the team schema `workspace.portfolio`) |
| Landing volume | `/Volumes/workspace/portfolio_monthly_dev/landing/incoming/YYYY-MM/` |
| Config | `config/pipeline_config_monthly_dev.yml` |
| Job | `run_monthly_pipeline` (job ID 824387683291203), parameter `config_path` = the dev config in the Git folder `/Users/ritvik.kohli@rotman.utoronto.ca/financial-model-monthly` |
| Run time | Full 5-month backfill about 22 min; one month about 8 min |
| App page | **Monthly review** in `ifc-cfo-intelligence` (`app/frontend/src/pages/Monthly.jsx`, `app/backend/monthly.py`) |
| App settings | `IFC_MONTHLY_SCHEMA=portfolio_monthly_dev`, `IFC_MONTHLY_JOB_ID=824387683291203` in `app/app.yaml` |
| App access | The app's service principal has USE SCHEMA, SELECT, EXECUTE, READ/WRITE VOLUME on the schema, and Can Manage Run on the job |

## Rebuild from scratch

1. Copy each month folder into the landing volume: `incoming/2026-06/`, …, `incoming/2026-10/` (October: the two
   original files only). Or run `test_files/make_demo_months` with `step = generate` and the dev `config_path`.
2. Run the job `run_monthly_pipeline` (or the notebook `01_data/run_monthly_pipeline` with the dev `config_path`).
3. For the correction demo: upload `synthetic_project_monitoring_2026-10_corrected.csv` for 2026-10 (app: Monthly
   review → Load a new month), or run `make_demo_months` with `step = reupload_october`, then run the job again.

**For presentations:** say these months are synthetic. Some clients behave in ways that do not match the WS3
recommendations (e.g. a Zansorzen Renewables project slips to Past Due in August), because the months were
generated, not observed.
