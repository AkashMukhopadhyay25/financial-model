"""
Monthly history: trends across reporting months and loading a new month.

Tables come from 01_data/run_monthly_pipeline (08_trends), in the monthly schema (IFC_MONTHLY_SCHEMA, default
portfolio_monthly_dev): kpi_monthly, compare_months(), project_month_changes, ops_monthly_loads, ops_schema_gate_log.
Uploads go to that schema's landing volume, incoming/YYYY-MM/, and start the run_monthly_pipeline job (IFC_MONTHLY_JOB_ID).
"""
import base64
import io
import os
import re

from .settings import get_settings
from .sql import get_db

MONTH_RE = re.compile(r"^20\d\d-(0[1-9]|1[0-2])$")
FILE_PATTERNS = [re.compile(r"^synthetic_ifc_projects_.*\.csv$"), re.compile(r"^synthetic_project_monitoring.*\.csv$")]
DIMENSIONS = ["Portfolio", "Region", "Industry", "Product line", "Department"]


def schema() -> str:
    return os.getenv("IFC_MONTHLY_SCHEMA") or "portfolio_monthly_dev"


def M(name: str) -> str:
    return f"{get_settings().catalog}.{schema()}.{name}"


def job_id() -> str:
    return os.getenv("IFC_MONTHLY_JOB_ID") or ""


def q(sql: str, params: dict = None) -> list:
    return get_db().query(sql, params)


def try_q(sql: str, params: dict = None) -> list:
    try:
        return q(sql, params)
    except Exception:
        return []


def status() -> dict:
    months_sql = f"SELECT DISTINCT month_label FROM {M('kpi_monthly')} ORDER BY month_label"
    loads_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, source, source_file, rows_loaded,
       CAST(loaded_at AS STRING) AS loaded_at, is_active
FROM {M('ops_monthly_loads')}
ORDER BY reporting_month DESC, loaded_at DESC"""
    gate_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, file_name, source, status, messages,
       CAST(checked_at AS STRING) AS checked_at
FROM {M('ops_schema_gate_log')}
ORDER BY checked_at DESC LIMIT 20"""
    return {"schema": f"{get_settings().catalog}.{schema()}", "months": [r["month_label"] for r in try_q(months_sql)],
            "loads": try_q(loads_sql), "gate": try_q(gate_sql), "job_configured": bool(job_id()),
            "dimensions": DIMENSIONS, "evidence": {"months": months_sql, "loads": loads_sql, "gate": gate_sql}}


def compare(month_a: str, month_b: str, dimension: str) -> dict:
    if not (MONTH_RE.match(month_a) and MONTH_RE.match(month_b)) or dimension not in DIMENSIONS:
        raise ValueError("Months must look like 2026-10 and the breakdown must be one of " + ", ".join(DIMENSIONS))
    sql = f"SELECT * FROM {M('compare_months')}(:month_a, :month_b, :dimension)"
    rows = q(sql, {"month_a": month_a, "month_b": month_b, "dimension": dimension})
    shown = sql.replace(":month_a", f"'{month_a}'").replace(":month_b", f"'{month_b}'").replace(":dimension", f"'{dimension}'")
    return {"rows": rows, "evidence": shown}


def series() -> dict:
    sql = f"""SELECT month_label, kpi_id, kpi_name, category, unit, better, value
FROM {M('kpi_monthly')}
WHERE dimension = 'Portfolio'
ORDER BY kpi_id, month_label"""
    return {"rows": q(sql), "evidence": sql}


def changes(month_a: str, month_b: str, change_type: str = "") -> dict:
    if not (MONTH_RE.match(month_a) and MONTH_RE.match(month_b)):
        raise ValueError("Months must look like 2026-10")
    where = "date_format(reporting_month, 'yyyy-MM') > :month_a AND date_format(reporting_month, 'yyyy-MM') <= :month_b"
    params = {"month_a": month_a, "month_b": month_b}
    summary_sql = f"""SELECT change_type, impact, count(*) AS projects, round(sum(amount_musd), 1) AS amount_musd
FROM {M('project_month_changes')}
WHERE {where}
GROUP BY change_type, impact
ORDER BY projects DESC"""
    out = {"summary": q(summary_sql, params), "evidence": summary_sql}
    if change_type:
        detail_sql = f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, client_name, project_name, region, industry,
       from_value, to_value, round(amount_musd, 2) AS amount_musd
FROM {M('project_month_changes')}
WHERE {where} AND change_type = :change_type
ORDER BY abs(amount_musd) DESC NULLS LAST
LIMIT 200"""
        out["detail"] = q(detail_sql, {**params, "change_type": change_type})
        out["detail_evidence"] = detail_sql
    return out


def upload(month: str, files: list) -> dict:
    """files: [{name, content_base64}]. Writes to incoming/<month>/ and starts the monthly pipeline job."""
    from databricks.sdk import WorkspaceClient

    if not MONTH_RE.match(month or ""):
        raise ValueError("Month must look like 2026-11")
    if not files:
        raise ValueError("Add the month's CSV files")
    bad = [f["name"] for f in files if not any(p.match(f["name"]) for p in FILE_PATTERNS)]
    if bad:
        raise ValueError(f"Unrecognised file name(s): {', '.join(bad)}. Expected synthetic_ifc_projects_*.csv "
                         "or synthetic_project_monitoring*.csv")
    already = any(r["month"] == month for r in try_q(
        f"SELECT DISTINCT date_format(reporting_month, 'yyyy-MM') AS month FROM {M('ops_monthly_loads')}"))
    w = WorkspaceClient()
    root = f"/Volumes/{get_settings().catalog}/{schema()}/landing/incoming/{month}"
    for f in files:
        w.files.upload(f"{root}/{f['name']}", io.BytesIO(base64.b64decode(f["content_base64"])), overwrite=True)
    run_id = None
    if job_id():
        run_id = w.jobs.run_now(job_id=int(job_id())).run_id
    return {"uploaded": [f["name"] for f in files], "folder": root, "replaces_existing_month": already,
            "run_id": run_id, "job_configured": bool(job_id())}


def runs() -> list:
    if not job_id():
        return []
    from databricks.sdk import WorkspaceClient

    out = []
    for r in WorkspaceClient().jobs.list_runs(job_id=int(job_id()), limit=5):
        st = r.state
        state = ""
        if st:
            state = (st.result_state.value if st.result_state else st.life_cycle_state.value if st.life_cycle_state else "")
        out.append({"run_id": r.run_id, "started_ms": r.start_time, "state": state,
                    "message": st.state_message if st else "", "url": r.run_page_url})
    return out
