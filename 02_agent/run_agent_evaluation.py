"""
Run the agents' paraphrase-consistency evaluation on Databricks (job "cloudstruck_agent_evaluation").

It runs the same code as the app (app/backend), so every agent run is also an MLflow trace in the experiment named in
config (serving.agents.mlflow_experiment). The evaluation itself is logged as an MLflow run in that experiment:
metrics per agent (phrasings passed, consistency, average latency) and the Markdown report as an artifact. Results also
go to the table ops_agent_evaluation, one row per phrasing.

Run it after any change to an agent's prompt, tools or model. Locally:  PYTHONPATH=. python -m app.backend.evaluate
"""
import base64
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:  # executed without __file__
        return Path.cwd().parent


def _mirror(root: Path) -> Path:
    """Serverless in this workspace cannot always read workspace files (OSError Errno 5). Copy app/backend and the
    config to local disk through the Workspace API, the same workaround the pipeline notebooks use."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.workspace import ExportFormat

    w = WorkspaceClient()
    dst = Path("/tmp/cloudstruck")
    for rel in ["app/__init__.py", "app/backend/__init__.py", "config/pipeline_config.yml", "config/market_outlook.yml"] + [
            f"app/backend/{o.path.rsplit('/', 1)[-1]}" for o in w.workspace.list(f"{root}/app/backend")
            if o.path.endswith(".py")]:
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = w.workspace.export(f"{root}/{rel}", format=ExportFormat.AUTO).content
            out.write_bytes(base64.b64decode(data) if data else b"")
        except Exception:
            if not out.exists():
                out.write_text("")
    return dst


def main():
    root = _repo_root()
    try:
        (root / "app" / "backend" / "agent_core.py").read_text()
        base = root
    except Exception:
        base = _mirror(root)
    sys.path.insert(0, str(base))

    import yaml

    cfg = yaml.safe_load((base / "config" / "pipeline_config.yml").read_text())
    env, srv = cfg.get("environment", {}), cfg.get("serving", {})
    os.environ.setdefault("IFC_DATA_MODE", "databricks")
    os.environ.setdefault("IFC_CATALOG", env.get("catalog", "workspace"))
    os.environ.setdefault("IFC_SCHEMA", env.get("schema", "portfolio"))
    os.environ.setdefault("IFC_WAREHOUSE_ID", srv.get("sql_warehouse_id", ""))
    os.environ.setdefault("IFC_AGENT_EXPERIMENT", (srv.get("agents") or {}).get("mlflow_experiment", ""))

    import uuid

    from app.backend import evaluate

    eid = uuid.uuid4().hex[:12]
    rows = evaluate.run_stress() + evaluate.run_allocation()
    evaluate.save(rows, eid)
    report = evaluate.report(rows, eid)
    passed = sum(r["passed"] for r in rows)
    print(report)
    print(f"{passed} of {len(rows)} phrasings consistent (eval {eid})")

    try:  # the evaluation as an MLflow run, next to the agents' traces
        import mlflow

        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(os.environ["IFC_AGENT_EXPERIMENT"])
        with mlflow.start_run(run_name=f"paraphrase-consistency-{eid}"):
            mlflow.set_tags({"eval_id": eid, "kind": "paraphrase_consistency"})
            for agent in ("stress_test", "capital_allocation"):
                rs = [r for r in rows if r["agent"] == agent]
                if rs:
                    mlflow.log_metric(f"{agent}_passed", sum(r["passed"] for r in rs))
                    mlflow.log_metric(f"{agent}_phrasings", len(rs))
                    mlflow.log_metric(f"{agent}_consistency", sum(r["passed"] for r in rs) / len(rs))
                    mlflow.log_metric(f"{agent}_avg_latency_s", sum(r["latency_ms"] for r in rs) / len(rs) / 1000)
            mlflow.log_metric("overall_consistency", passed / len(rows))
            mlflow.log_text(report, "agent_evaluation_report.md")
    except Exception as e:
        print(f"MLflow run not logged ({type(e).__name__}: {e}); results are in ops_agent_evaluation")

    if passed < len(rows):
        raise SystemExit(f"Consistency below 100%: {passed} of {len(rows)}. See the report above.")


if __name__ == "__main__":
    main()
