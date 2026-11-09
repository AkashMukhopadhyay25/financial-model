"""Monthly history: reporting months, the load registry and the `raw_<source>_current` views.

How a month is identified
-------------------------
Files are dropped into a month folder under the landing zone: `incoming/2026-10/`. The folder name (YYYY-MM) is the
file's reporting month; nobody has to rename files. The gate keeps the month in every folder it moves the file to
(`accepted/2026-10/<source>/`, `held/2026-10/`, `loaded/2026-10/<source>/`).

Override rule
-------------
`ops_monthly_loads` has one row per Raw load: month, source, file, fingerprint, `is_active`. For each (month, source)
exactly one load is active: the newest. Uploading a corrected October file makes it the active October load; the
earlier October load is marked superseded (`superseded_by_load_id`), and its rows stay in Raw for audit.
Downstream, only October's partition of the history tables is rebuilt.

Latest data
-----------
The latest month = the highest month that has an active load for EVERY source (a month with only a projects file is
incomplete and is skipped). `raw_<source>_current` points at the active load of the month being processed, which is
the latest month except while an older month is being reprocessed (see 01_data/run_monthly_pipeline).

Plain Python plus a `spark` argument, so it imports on Databricks and the month helpers can be tested locally.
"""
import re
from datetime import date

from ifc_common import T

MONTH_FOLDER = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
REGISTRY = "ops_monthly_loads"
SNAPSHOTS = "ops_monthly_snapshots"


# ---- Month helpers -------------------------------------------------------------------------------------------------

def month_from_folder(name: str):
    """'2026-10' -> date(2026, 10, 1); anything else -> None."""
    m = MONTH_FOLDER.match(name or "")
    return date(int(m.group(1)), int(m.group(2)), 1) if m else None


def month_label(d) -> str:
    """date(2026, 10, 1) -> '2026-10'."""
    return f"{d.year:04d}-{d.month:02d}"


def parse_month(text: str):
    """Accepts '2026-10', '2026-10-01' or '2026-10-31' and returns the first day of that month."""
    m = re.match(r"^(\d{4})-(\d{2})", (text or "").strip())
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"Not a month: {text!r}. Use YYYY-MM, e.g. 2026-10.")
    return date(int(m.group(1)), int(m.group(2)), 1)


# ---- Load registry -------------------------------------------------------------------------------------------------

def ensure_registry(spark, cfg):
    spark.sql(f"""
    CREATE TABLE IF NOT EXISTS {T(cfg, REGISTRY)} (
      load_id STRING, reporting_month DATE, source STRING, source_file STRING, file_sha256 STRING,
      rows_loaded INT, loaded_at TIMESTAMP, is_active BOOLEAN, superseded_by_load_id STRING, superseded_at TIMESTAMP,
      check_message STRING)
    COMMENT 'One row per Raw load, with its reporting month (from the landing folder incoming/YYYY-MM/). Exactly one active load per month and source: a re-upload for the same month supersedes the earlier load, whose rows stay in Raw for audit.'
    """)


def register_load(spark, cfg, rec: dict):
    """Make `rec` the active load for its (month, source); the previous active load is marked superseded."""
    ensure_registry(spark, cfg)
    reg = T(cfg, REGISTRY)
    month = rec["reporting_month"].isoformat()
    spark.sql(f"""
      UPDATE {reg}
      SET is_active = false, superseded_by_load_id = '{rec['load_id']}', superseded_at = current_timestamp()
      WHERE reporting_month = DATE'{month}' AND source = '{rec['source']}' AND is_active""")
    msg = (rec.get("check_message") or "").replace("'", "''")
    fname = rec["source_file"].replace("'", "''")
    spark.sql(f"""
      INSERT INTO {reg} VALUES ('{rec['load_id']}', DATE'{month}', '{rec['source']}', '{fname}',
        '{rec['file_sha256']}', {int(rec['rows_loaded'])}, TIMESTAMP'{rec['loaded_at']}', true, NULL, NULL,
        {("'" + msg + "'") if msg else 'NULL'})""")


def active_loads(spark, cfg) -> dict:
    """{(month, source): row} for every active load."""
    if not spark.catalog.tableExists(T(cfg, REGISTRY)):
        return {}
    rows = spark.sql(f"SELECT * FROM {T(cfg, REGISTRY)} WHERE is_active").collect()
    return {(r.reporting_month, r.source): r for r in rows}


def active_sha(spark, cfg, month, source):
    row = active_loads(spark, cfg).get((month, source))
    return row.file_sha256 if row else None


def complete_months(spark, cfg, sources) -> list:
    """Months with an active load for every source, oldest first."""
    act = active_loads(spark, cfg)
    months = {m for (m, _) in act}
    return sorted(m for m in months if all((m, s) in act for s in sources))


def incomplete_months(spark, cfg, sources) -> dict:
    """{month: [missing sources]} for months that have some, but not all, sources."""
    act = active_loads(spark, cfg)
    months = {m for (m, _) in act}
    return {m: [s for s in sources if (m, s) not in act] for m in sorted(months)
            if not all((m, s) in act for s in sources)}


def latest_month(spark, cfg, sources):
    months = complete_months(spark, cfg, sources)
    return months[-1] if months else None


# ---- Views ----------------------------------------------------------------------------------------------------------

def point_current_views(spark, cfg, contracts: dict, month):
    """Point raw_<source>_current at the active load of `month` for every source; also (re)create raw_<source>_active."""
    act = active_loads(spark, cfg)
    reg = T(cfg, REGISTRY)
    for source, contract in contracts.items():
        raw = T(cfg, contract["targets"]["raw"])
        load = act.get((month, source))
        if load is None:
            raise RuntimeError(f"No active {source} load for {month_label(month)}. Upload it to incoming/{month_label(month)}/.")
        spark.sql(f"""
          CREATE OR REPLACE VIEW {raw}_current
          COMMENT 'Active load of {raw} for reporting month {month_label(month)} ({load.source_file}). Re-pointed by the pipeline to the month being processed; normally the latest month.'
          AS SELECT * FROM {raw} WHERE _load_id = '{load.load_id}'""")
        spark.sql(f"""
          CREATE OR REPLACE VIEW {raw}_active
          COMMENT 'Active load of {raw} for every reporting month (superseded uploads excluded). Audit view.'
          AS SELECT r.* FROM {raw} r JOIN {reg} g ON r._load_id = g.load_id WHERE g.is_active""")
    print(f"raw_*_current now point at {month_label(month)}: "
          + ", ".join(f"{s} = {act[(month, s)].source_file}" for s in contracts))


# ---- What still needs processing ---------------------------------------------------------------------------------------

def months_to_process(spark, cfg, sources) -> list:
    """Complete months whose active loads differ from the loads their last snapshot was built from (or never built)."""
    act = active_loads(spark, cfg)
    snap = {}
    if spark.catalog.tableExists(T(cfg, SNAPSHOTS)):
        snap = {r.reporting_month: r for r in spark.table(T(cfg, SNAPSHOTS)).collect()}
    todo = []
    for m in complete_months(spark, cfg, sources):
        s = snap.get(m)
        loads = {src: act[(m, src)].load_id for src in sources}
        if s is None or (s.projects_load_id, s.monitoring_load_id) != (loads.get("projects"), loads.get("monitoring")):
            todo.append(m)
    return todo
