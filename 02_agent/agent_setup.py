# Databricks notebook source
# MAGIC %md
# MAGIC # Agent setup (shared)
# MAGIC
# MAGIC Run by `02_agent_capabilities` and `03_build_agent` with `%run ./agent_setup`. It makes the app's backend
# MAGIC (`03_demo/app/backend`) importable, so these notebooks use exactly the code the app runs, and points it at the
# MAGIC catalog, schema and SQL warehouse in `00_setup/config/pipeline_config.yml`.

# COMMAND ----------

import base64
import os
import sys
from pathlib import Path

import yaml


def _repo_root() -> Path:
    """The folder that holds 00_setup/, 02_agent/ and 03_demo/ (one level above this notebook)."""
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # noqa: F821
        return Path(nb if nb.startswith("/Workspace") else "/Workspace" + nb).parent.parent
    except Exception:
        return Path.cwd().parent


def _mirror(root: Path) -> Path:
    """Serverless in this workspace cannot always read workspace files (OSError Errno 5): copy the app backend and the
    config to local disk through the Workspace API, as the pipeline notebooks do."""
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.workspace import ExportFormat, ObjectType

    w = WorkspaceClient()
    ws_root = str(root)[len("/Workspace"):]
    dst = Path("/tmp/cloudstruck")
    for sub in ["03_demo/app/backend", "00_setup/config"]:
        for o in w.workspace.list(f"{ws_root}/{sub}"):
            if o.object_type == ObjectType.FILE and o.path.endswith((".py", ".json", ".yml")):
                out = dst / o.path[len(ws_root) + 1:]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(base64.b64decode(w.workspace.export(o.path, format=ExportFormat.AUTO).content or b""))
    (dst / "03_demo" / "app" / "__init__.py").write_text("")
    return dst


ROOT = _repo_root()
try:
    (ROOT / "03_demo" / "app" / "backend" / "agent_core.py").read_text()
    BASE = ROOT
except Exception:
    BASE = _mirror(ROOT)
sys.path.insert(0, str(BASE / "03_demo"))  # the app package: 03_demo/app

CFG = yaml.safe_load((BASE / "00_setup" / "config" / "pipeline_config.yml").read_text())
_env, _srv = CFG.get("environment", {}), CFG.get("serving", {})
os.environ.setdefault("IFC_DATA_MODE", "databricks")
os.environ.setdefault("IFC_CATALOG", _env.get("catalog", "workspace"))
os.environ.setdefault("IFC_SCHEMA", _env.get("schema", "portfolio"))
os.environ.setdefault("IFC_WAREHOUSE_ID", _srv.get("sql_warehouse_id", ""))
os.environ.setdefault("IFC_AGENT_EXPERIMENT", (_srv.get("agents") or {}).get("mlflow_experiment", ""))
print(f"App backend from {BASE / '03_demo' / 'app'} · data in {os.environ['IFC_CATALOG']}.{os.environ['IFC_SCHEMA']}")
