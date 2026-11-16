"""
App settings. Order of precedence for each value:
  1. environment variables set by app.yaml (IFC_CATALOG, IFC_SCHEMA, IFC_WAREHOUSE_ID, IFC_GENIE_SPACE_ID);
  2. config/pipeline_config.yml, when the app runs from the repo (local development, or deployed from the repo root).

IFC_DATA_MODE = "databricks" (default when a warehouse ID is known) or "local" (DuckDB preview built from data/).
"""
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
REPO_CONFIG = APP_DIR.parent / "config" / "pipeline_config.yml"


def _repo_config() -> dict:
    if not REPO_CONFIG.is_file():
        return {}
    try:
        import yaml

        return yaml.safe_load(REPO_CONFIG.read_text()) or {}
    except Exception:
        return {}


@dataclass(frozen=True)
class Settings:
    catalog: str
    schema: str
    warehouse_id: str
    genie_space_id: str
    data_mode: str  # "databricks" | "local"
    ecl_loss_rate: float
    stress_agent_model: str
    allocation_agent_model: str
    alloc_min_active_projects: int
    alloc_max_segment_share: float

    def table(self, name: str) -> str:
        """Fully qualified name on Databricks; bare name in the local DuckDB preview."""
        return name if self.data_mode == "local" else f"{self.catalog}.{self.schema}.{name}"


@lru_cache
def get_settings() -> Settings:
    cfg = _repo_config()
    env, srv, biz = cfg.get("environment", {}), cfg.get("serving", {}), cfg.get("business", {})
    warehouse = os.getenv("IFC_WAREHOUSE_ID") or srv.get("sql_warehouse_id") or ""
    mode = os.getenv("IFC_DATA_MODE") or ("databricks" if os.getenv("DATABRICKS_APP_NAME") else "local")
    return Settings(
        catalog=os.getenv("IFC_CATALOG") or env.get("catalog") or "ifc_challenge",
        schema=os.getenv("IFC_SCHEMA") or env.get("schema") or "portfolio",
        warehouse_id=warehouse,
        genie_space_id=os.getenv("IFC_GENIE_SPACE_ID") or srv.get("genie_space_id") or "",
        data_mode=mode,
        ecl_loss_rate=float(os.getenv("IFC_ECL_LOSS_RATE") or biz.get("ecl_loss_rate") or 0.6),
        stress_agent_model=os.getenv("IFC_STRESS_AGENT_MODEL") or (srv.get("agents") or {}).get("stress_test_model")
        or "databricks-qwen3-next-80b-a3b-instruct",
        allocation_agent_model=os.getenv("IFC_ALLOCATION_AGENT_MODEL")
        or (srv.get("agents") or {}).get("capital_allocation_model") or "databricks-qwen3-next-80b-a3b-instruct",
        alloc_min_active_projects=int(os.getenv("IFC_ALLOC_MIN_ACTIVE") or (biz.get("capital_allocation") or {}).get("min_active_projects") or 10),
        alloc_max_segment_share=float(os.getenv("IFC_ALLOC_MAX_SHARE") or (biz.get("capital_allocation") or {}).get("max_segment_share") or 0.25),
    )
