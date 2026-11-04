"""
Local test adapter: runs Stage 3's generated SQL on SQLite instead of Spark.

Only a handful of things differ from Spark and are translated here:
  TRY_CAST(x AS DATE/INT/DOUBLE) -> try_date/try_int/try_double (Python functions)
  x RLIKE 'p'                    -> x REGEXP 'p'
  CAST(x AS STRING)              -> CAST(x AS TEXT)
  current_timestamp()            -> CURRENT_TIMESTAMP
  catalog.schema.table           -> table (one SQLite database; names keep their layer prefix)
Everything else (CTEs, CASE, CONCAT_WS, window functions, subqueries) is the same SQL.
"""
import re
import sqlite3
from datetime import datetime
from pathlib import Path


def _try_date(s):
    if s is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s)):
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _try_int(s):
    return int(s) if s is not None and re.fullmatch(r"-?\d+", str(s).strip()) else None


def _try_double(s):
    try:
        return float(s) if s is not None else None
    except ValueError:
        return None


class SqliteDialect:
    name = "sqlite"
    CAST_FUNCS = {"date": "try_date", "integer": "try_int", "double": "try_double"}

    def __init__(self, db_dir):
        db_dir = Path(db_dir)
        db_dir.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_dir / "main.db")
        self.conn.create_function("try_date", 1, _try_date, deterministic=True)
        self.conn.create_function("try_int", 1, _try_int, deterministic=True)
        self.conn.create_function("try_double", 1, _try_double, deterministic=True)
        self.conn.create_function("regexp", 2,
                                  lambda p, s: s is not None and re.search(p, s) is not None, deterministic=True)

    def table(self, short_name):
        return short_name

    def cast(self, expr, typ):
        return f"{self.CAST_FUNCS[typ]}({expr})"

    def regex(self, expr, pattern):
        return f"({expr} REGEXP '{pattern}')"

    def adapt(self, sql):
        sql = re.sub(r"AS STRING\)", "AS TEXT)", sql)
        return sql.replace("current_timestamp()", "CURRENT_TIMESTAMP")

    def execute(self, sql):
        self.conn.executescript(self.adapt(sql))

    def query(self, sql):
        cur = self.conn.execute(self.adapt(sql))
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def table_exists(self, name):
        return bool(self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name = ?", (name,)).fetchone())

    def create_or_replace_table(self, name, select_sql):
        self.conn.execute(f"DROP TABLE IF EXISTS {name}")
        self.conn.execute(self.adapt(f"CREATE TABLE {name} AS {select_sql}"))
        self.conn.commit()

    def create_temp_view(self, name, select_sql):
        self.conn.execute(f"DROP VIEW IF EXISTS {name}")
        self.conn.execute(self.adapt(f"CREATE TEMP VIEW {name} AS {select_sql}"))

    def append_rows(self, name, columns, rows):
        types = {"int": "INTEGER", "string": "TEXT"}
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS {name} ("
                          + ", ".join(f"{c} {types[t]}" for c, t in columns) + ")")
        self.conn.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in columns)})",
                              [[r.get(c) for c, _ in columns] for r in rows])
        self.conn.commit()

    # --- test helper: load Stage 2's local raw output and create the _current view ---
    def load_raw_csv(self, csv_path, short_name):
        import pandas as pd

        df = pd.read_csv(csv_path, dtype=str, keep_default_na=False, na_values=[""])
        tbl = short_name
        cols = list(df.columns)
        self.conn.execute(f"DROP TABLE IF EXISTS {short_name}")
        self.conn.execute(f"CREATE TABLE {short_name} (" + ", ".join(f'"{c}" TEXT' for c in cols) + ")")
        rows = [[None if pd.isna(x) else x for x in r] for r in df.itertuples(index=False, name=None)]
        self.conn.executemany(f"INSERT INTO {short_name} VALUES ({', '.join('?' for _ in cols)})", rows)
        self.conn.execute(f"DROP VIEW IF EXISTS {short_name}_current")
        self.conn.execute(f"CREATE VIEW {short_name}_current AS SELECT * FROM {tbl} "
                          f"WHERE _loaded_at = (SELECT MAX(_loaded_at) FROM {tbl})")
        self.conn.commit()
