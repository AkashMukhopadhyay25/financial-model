"""
One way to run SQL, two engines:
  DatabricksSQL  Statement Execution API on the SQL warehouse (the deployed app; runs as the app's service principal)
  LocalSQL       DuckDB preview database (local development)

Queries use named parameters `:name` (Databricks syntax); LocalSQL rewrites them to DuckDB's `$name`.
Never format user input into SQL text: pass it as a parameter.
"""
import re
import threading
import time
from decimal import Decimal
from functools import lru_cache

from .settings import get_settings

NUMERIC = {"INT", "BIGINT", "SMALLINT", "TINYINT", "LONG", "SHORT", "BYTE"}
FLOATS = {"DOUBLE", "FLOAT", "DECIMAL"}


def _convert(value, type_name: str):
    if value is None:
        return None
    t = (type_name or "").upper()
    if t in NUMERIC:
        return int(value)
    if t in FLOATS:
        return float(value)
    if t == "BOOLEAN":
        return str(value).lower() == "true"
    return value


def statement_to_rows(resp) -> tuple:
    """(columns, rows as dicts) from a StatementResponse (used for warehouse queries and Genie results)."""
    cols = [(c.name, c.type_name.value if hasattr(c.type_name, "value") else str(c.type_name))
            for c in (resp.manifest.schema.columns or [])] if resp.manifest and resp.manifest.schema else []
    data = (resp.result.data_array if resp.result else None) or []
    rows = [{name: _convert(v, t) for (name, t), v in zip(cols, r)} for r in data]
    return [c for c, _ in cols], rows


class DatabricksSQL:
    def __init__(self, warehouse_id: str):
        from databricks.sdk import WorkspaceClient

        if not warehouse_id:
            raise RuntimeError("No SQL warehouse configured: add the 'sql-warehouse' resource to the app.")
        self.w = WorkspaceClient()
        self.warehouse_id = warehouse_id

    def query(self, sql: str, params: dict = None) -> list:
        from databricks.sdk.service.sql import (Disposition, Format, StatementParameterListItem,
                                                StatementState)

        plist = [StatementParameterListItem(name=k, value=None if v is None else str(v)) for k, v in (params or {}).items()]
        resp = self.w.statement_execution.execute_statement(
            statement=sql, warehouse_id=self.warehouse_id, parameters=plist or None, wait_timeout="50s",
            disposition=Disposition.INLINE, format=Format.JSON_ARRAY)
        deadline = time.time() + 120
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING) and time.time() < deadline:
            time.sleep(1)
            resp = self.w.statement_execution.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if resp.status.error else resp.status.state
            raise RuntimeError(f"SQL failed: {msg}")
        return statement_to_rows(resp)[1]


class LocalSQL:
    def __init__(self):
        import duckdb

        from .local_preview import build

        self.con = duckdb.connect(str(build()))
        self.lock = threading.Lock()

    def query(self, sql: str, params: dict = None) -> list:
        sql = re.sub(r"(?<![:\w]):([A-Za-z_]\w*)", r"$\1", sql)
        with self.lock:
            cur = self.con.execute(sql, params or {})
            if cur.description is None:
                return []
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                out.append({c: (float(v) if isinstance(v, Decimal) else v.isoformat() if hasattr(v, "isoformat") else v)
                            for c, v in zip(cols, r)})
            return out


@lru_cache
def get_db():
    s = get_settings()
    return LocalSQL() if s.data_mode == "local" else DatabricksSQL(s.warehouse_id)
