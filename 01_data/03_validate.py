# Databricks notebook source
# MAGIC %md
# MAGIC # Stage 3 — Validate
# MAGIC
# MAGIC Turns the latest Raw load (`raw_<source>_current`) into a **Validated** table: typed, standardized and
# MAGIC flagged. Everything this stage does is defined in the data contracts and `pipeline_config.yml`;
# MAGIC this notebook only turns those definitions into SQL and runs it.
# MAGIC
# MAGIC | Output | What it holds |
# MAGIC |---|---|
# MAGIC | `validated_<source>` | Rows that passed. Proper types (dates, numbers), standardized values (with the value as received kept where the contract says `keep_original_as`, e.g. `region_as_reported`), the contract's `derived_columns` (e.g. `is_climate_related`), one `flag_<name>` column per flag rule, plus roll-ups: `needs_review`, `dq_max_severity`, `review_owners`, `dq_messages`. |
# MAGIC | `validated_<source>_quarantine` | Rows that are unusable (missing key, unparseable value, invalid category, duplicate key, negative amount), kept as raw text with `quarantine_reasons`. |
# MAGIC | `validated_<source>_dq_issues` | One row per flag hit: record, rule, severity, owner, message. This is what the app shows when a user clicks "Needs review". |
# MAGIC | `ops_dq_run_summary` | One row per rule per run: how many rows it hit, compared with the count found when profiling. |
# MAGIC
# MAGIC **Two levels of problem:**
# MAGIC - **Quarantine** = the row can't be used. It's removed from the validated table and parked with its reasons.
# MAGIC - **Flag** = the row is usable but needs attention. It stays, and the flag travels with it to every answer.
# MAGIC
# MAGIC **Safety checks before anything is replaced:**
# MAGIC 1. If more than `max_quarantine_share` of rows would be quarantined, the stage stops and the existing
# MAGIC    validated tables are left untouched.
# MAGIC 2. After writing, rows in = validated + quarantined, or the run fails.
# MAGIC
# MAGIC `raw_<source>_current` is the active load of the reporting month being processed (normally the latest month;
# MAGIC see `ops_monthly_loads` and `run_monthly_pipeline`). `_reporting_month` travels with every row.
# MAGIC
# MAGIC Validated tables are **rebuilt** each run from the latest Raw load (history lives in Raw), so the result
# MAGIC always reflects the current contract and thresholds. Sources run in dependency order: `projects` first,
# MAGIC because monitoring rules check against validated projects.

# COMMAND ----------

# MAGIC %pip install pyyaml --quiet

# COMMAND ----------

import json
import re
import uuid
from datetime import datetime, timezone

# ---- Find the repo root and import the shared helpers (same cell in every pipeline notebook) ----------
import os
import sys
from pathlib import Path


def _repo_root():
    """Folder holding config/ and 00_setup/. Tries this file, the working directory, then the notebook path."""
    starts = []
    if "__file__" in globals():
        starts.append(Path(__file__).resolve().parent)
    starts.append(Path(os.getcwd()))
    try:
        nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # noqa: F821
        starts.append(Path(nb if nb.startswith("/Workspace") else "/Workspace" + nb).parent)
    except Exception:
        pass
    for start in starts:
        for folder in [start, *start.parents]:
            if (folder / "00_setup" / "ifc_common.py").is_file():
                return folder
    raise FileNotFoundError("Could not find the repo root (the folder that holds 00_setup/ifc_common.py). "
                            f"Tried: {[str(s) for s in starts]}")


REPO_ROOT = _repo_root()
if str(REPO_ROOT / "00_setup") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "00_setup"))
from ifc_common import T, load_config, load_contracts, load_order, resolve_config_path  # noqa: E402

try:
    dbutils.widgets.text("config_path", "", "Config path (blank = repo config)")  # noqa: F821
    _widget = dbutils.widgets.get("config_path")  # noqa: F821
except NameError:
    _widget = None
CONFIG_PATH = resolve_config_path(_widget, REPO_ROOT)
SHOW_SQL = False   # set True to print every generated SQL statement

try:
    spark  # noqa: F821
    ON_DATABRICKS = True
except NameError:
    ON_DATABRICKS = False

AUDIT_COLS = ["_load_id", "_reporting_month", "_loaded_at", "_source_file", "_file_sha256", "_source_row_number"]
SEVERITY_ORDER = ["high", "warning", "info"]

# COMMAND ----------

# MAGIC %md ## Config, contracts, and the SQL engine adapter

# COMMAND ----------


class SparkDialect:
    """Runs the generated SQL on Databricks (Spark SQL + Delta tables in Unity Catalog)."""

    name = "spark"
    CAST_TYPES = {"date": "DATE", "integer": "INT", "double": "DOUBLE"}

    def __init__(self, cfg):
        self.cfg = cfg

    def table(self, short_name):
        return T(self.cfg, short_name)

    def cast(self, expr, typ):
        return f"TRY_CAST({expr} AS {self.CAST_TYPES[typ]})"

    def regex(self, expr, pattern):
        return f"({expr} RLIKE '{pattern}')"

    def adapt(self, sql):
        return sql

    def execute(self, sql):
        spark.sql(self.adapt(sql))  # noqa: F821

    def query(self, sql):
        return [r.asDict() for r in spark.sql(self.adapt(sql)).collect()]  # noqa: F821

    def table_exists(self, name):
        return spark.catalog.tableExists(name)  # noqa: F821

    def create_or_replace_table(self, name, select_sql):
        self.execute(f"CREATE OR REPLACE TABLE {name} AS {select_sql}")

    def create_temp_view(self, name, select_sql):
        self.execute(f"CREATE OR REPLACE TEMPORARY VIEW {name} AS {select_sql}")

    def append_rows(self, name, columns, rows):
        from pyspark.sql.types import IntegerType, StringType, StructField, StructType

        types = {"int": IntegerType(), "string": StringType()}
        schema = StructType([StructField(c, types[t]) for c, t in columns])
        spark.createDataFrame([[r.get(c) for c, _ in columns] for r in rows], schema) \
            .write.mode("append").saveAsTable(name)  # noqa: F821


# COMMAND ----------

# MAGIC %md ## SQL generation (pure Python: reads the contract, returns SQL text)

# COMMAND ----------


def q(text) -> str:
    """SQL string literal."""
    return "'" + str(text).replace("'", "''") + "'"


def flatten(d: dict, prefix="") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def render(sql: str, params: dict, valid_view: str) -> str:
    """Fill ${config.values} and {valid} in a rule's SQL."""
    def sub(m):
        key = m.group(1)
        if key not in params:
            raise KeyError(f"Rule refers to ${{{key}}}, which is not in pipeline_config.yml thresholds.")
        v = params[key]
        if isinstance(v, list):
            return ", ".join(q(x) for x in v) if v else "'__none__'"
        return str(v)

    sql = re.sub(r"\$\{([A-Za-z0-9_.]+)\}", sub, sql)
    return sql.replace("{valid}", valid_view)


def any_of(conds: list) -> str:
    return "(" + " OR ".join(f"({c})" for c in conds) + ")" if conds else "FALSE"


def build_statements(contract: dict, cfg: dict, d, run_id: str) -> dict:
    """Return every SQL statement for one source, keyed by step name, plus metadata."""
    c = contract["contract"]
    src = c["name"]
    schema = contract["schema"]
    pk = c["primary_key"]
    version = str(c["version"])
    params = flatten(cfg.get("thresholds", {}))

    v_typed, v_cast, v_checked, v_valid, v_flagged, v_final = (
        f"_v3_{src}_{s}" for s in ["typed", "cast", "checked", "valid", "flagged", "final"])
    raw_current = d.table(contract["targets"]["raw"]) + "_current"

    # 1. Trim every value; blank becomes NULL. Keep raw text as <col>__raw.
    typed = "SELECT " + ", ".join([f"r.{a}" for a in AUDIT_COLS] +
                                  [f"NULLIF(TRIM(r.{col['target']}), '') AS {col['target']}__raw" for col in schema]) \
        + f" FROM {raw_current} r"

    # 2. Convert types, standardize values, join lookup columns (cross-table checks).
    cast_cols = []
    for col in schema:
        t, raw = col["target"], f"t.{col['target']}__raw"
        if col["type"] == "string":
            std = col.get("standardize") or {}
            if std:
                whens = " ".join(f"WHEN {q(k)} THEN {q(v)}" for k, v in std.items())
                cast_cols.append(f"CASE {raw} {whens} ELSE {raw} END AS {t}")
                cast_cols.append(f"{raw} AS {t}__original")
            else:
                cast_cols.append(f"{raw} AS {t}")
        else:
            cast_cols.append(f"{d.cast(raw, col['type'])} AS {t}")
    cast_cols.append(f"COUNT(*) OVER (PARTITION BY t.{pk}__raw) AS _pk_count")

    join = ""
    lookup = contract.get("lookup")
    if lookup:
        lk = lookup["key"]
        cast_cols.append(f"l.{lk} AS p_{lk}")
        cast_cols += [f"l.{lc} AS p_{lc}" for lc in lookup["columns"]]
        join = f" LEFT JOIN {d.table(lookup['table'])} l ON t.{lk}__raw = l.{lk}"
    cast = "SELECT t.*, " + ", ".join(cast_cols) + f" FROM {v_typed} t" + join

    # 3. Quarantine checks: automatic ones from the schema, plus custom quarantine rules.
    checks = {"required": [], "type": [], "allowed": [], "pattern": [], "duplicate_key": [], "custom": []}
    reasons = []

    def add(category, cond, reason_sql):
        checks[category].append(cond)
        reasons.append(f"CASE WHEN {cond} THEN {reason_sql} END")

    for col in schema:
        t = col["target"]
        if col.get("required"):
            add("required", f"{t}__raw IS NULL", q(f"Missing required value: {t}"))
        if col["type"] != "string":
            label = q("Not a valid " + col["type"] + ": " + t + " = ")
            add("type", f"{t}__raw IS NOT NULL AND {t} IS NULL", f"CONCAT({label}, {t}__raw)")
        if col.get("allowed"):
            vals = ", ".join(str(v) if isinstance(v, int) else q(v) for v in col["allowed"])
            add("allowed", f"{t} IS NOT NULL AND {t} NOT IN ({vals})",
                f"CONCAT({q(f'Value not allowed: {t} = ')}, {t}__raw)")
        if col.get("pattern"):
            add("pattern", f"{t} IS NOT NULL AND NOT {d.regex(t, col['pattern'])}",
                f"CONCAT({q(f'Wrong format: {t} = ')}, {t}__raw)")
    add("duplicate_key", "_pk_count > 1", f"CONCAT({q(f'Duplicate {pk}: ')}, {pk}__raw)")
    for rule in contract.get("quarantine_rules", []):
        add("custom", render(rule["when"], params, v_cast), q(f"{rule['id']}: {rule['description']}"))

    checked = ("SELECT c.*, "
               + ", ".join(f"COALESCE({any_of(conds)}, FALSE) AS q_{cat}" for cat, conds in checks.items())
               + ", CONCAT_WS('; ', " + ", ".join(reasons) + ") AS quarantine_reasons"
               + f" FROM {v_cast} c")
    valid = f"SELECT * FROM {v_checked} WHERE quarantine_reasons = ''"

    # 4. Flags.
    rules = contract.get("flag_rules", [])
    flag_cols = [f"COALESCE(({render(r['when'], params, v_valid)}), FALSE) AS flag_{r['name']}" for r in rules]
    flagged = "SELECT v.*" + "".join(", " + fc for fc in flag_cols) + f" FROM {v_valid} v"

    # 5. Roll-ups.
    def flags_where(pred):
        return [f"flag_{r['name']}" for r in rules if pred(r)]

    sev_case = "CASE " + " ".join(
        f"WHEN {any_of(flags_where(lambda r, s=s: r['severity'] == s))} THEN {q(s)}" for s in SEVERITY_ORDER
    ) + " ELSE 'none' END"
    review_flags = flags_where(lambda r: r["severity"] in ("high", "warning"))
    owners = sorted({r["owner"] for r in rules if r["severity"] in ("high", "warning")})
    owner_parts = [f"CASE WHEN {any_of(flags_where(lambda r, o=o: r['owner'] == o and r['severity'] in ('high', 'warning')))} "
                   f"THEN {q(o)} END" for o in owners]
    rollups = [
        "CONCAT_WS(',', " + ", ".join(f"CASE WHEN flag_{r['name']} THEN {q(r['id'])} END" for r in rules) + ") AS dq_flag_ids",
        "(" + " + ".join(f"CASE WHEN flag_{r['name']} THEN 1 ELSE 0 END" for r in rules) + ") AS dq_flag_count",
        f"{sev_case} AS dq_max_severity",
        f"COALESCE({any_of(review_flags)}, FALSE) AS needs_review",
        "CONCAT_WS(', ', " + (", ".join(owner_parts) or "NULL") + ") AS review_owners",
        "CONCAT_WS(' | ', " + ", ".join(
            f"CASE WHEN flag_{r['name']} THEN {render(r['message'], params, v_valid)} END" for r in rules
        ) + ") AS dq_messages",
    ] if rules else ["'' AS dq_flag_ids", "0 AS dq_flag_count", "'none' AS dq_max_severity",
                     "FALSE AS needs_review", "'' AS review_owners", "'' AS dq_messages"]
    final = "SELECT f.*, " + ", ".join(rollups) + f" FROM {v_flagged} f"

    run_cols = (f"{q(version)} AS _contract_version, {q(run_id)} AS _validation_run_id, "
                "current_timestamp() AS _validated_at")

    # Value as received, kept next to a standardized column (e.g. region_as_reported).
    originals = [f"{col['target']}__original AS {col['keep_original_as']}"
                 for col in schema if col.get("keep_original_as") and col.get("standardize")]
    # Simple columns computed from validated columns (e.g. is_climate_related).
    derived = [f"({render(dc['sql'], params, v_valid)}) AS {dc['name']}" for dc in contract.get("derived_columns", [])]

    out_validated = ("SELECT " + ", ".join([col["target"] for col in schema] + originals + derived)
                     + "".join(f", flag_{r['name']}" for r in rules)
                     + ", dq_flag_ids, dq_flag_count, dq_max_severity, needs_review, review_owners, dq_messages, "
                     + ", ".join(AUDIT_COLS) + ", " + run_cols + f" FROM {v_final}")

    out_quarantine = ("SELECT " + ", ".join(f"{col['target']}__raw AS {col['target']}" for col in schema)
                      + ", quarantine_reasons, " + ", ".join(AUDIT_COLS) + ", " + run_cols
                      + f" FROM {v_checked} WHERE quarantine_reasons <> ''")

    issue_selects = [
        f"SELECT {pk} AS record_key, {q(src)} AS source, {q(r['id'])} AS rule_id, {q(r['name'])} AS rule_name, "
        f"{q(r['severity'])} AS severity, {q(r['owner'])} AS owner, {q(r['description'])} AS description, "
        f"{render(r['message'], params, v_valid)} AS message, _source_file, _source_row_number, "
        f"{q(run_id)} AS _validation_run_id FROM {v_flagged} WHERE flag_{r['name']}"
        for r in rules
    ]
    out_issues = " UNION ALL ".join(issue_selects) if issue_selects else None

    counts = ("SELECT COUNT(*) AS rows_in, "
              "SUM(CASE WHEN quarantine_reasons <> '' THEN 1 ELSE 0 END) AS quarantined, "
              + ", ".join(f"SUM(CASE WHEN q_{cat} THEN 1 ELSE 0 END) AS q_{cat}" for cat in checks)
              + f" FROM {v_checked}")
    flag_counts = ("SELECT " + ", ".join(f"SUM(CASE WHEN flag_{r['name']} THEN 1 ELSE 0 END) AS flag_{r['name']}"
                                         for r in rules) + f" FROM {v_final}") if rules else None

    return {
        "views": [(v_typed, typed), (v_cast, cast), (v_checked, checked),
                  (v_valid, valid), (v_flagged, flagged), (v_final, final)],
        "counts": counts, "flag_counts": flag_counts,
        "validated": out_validated, "quarantine": out_quarantine, "issues": out_issues,
        "raw_current": raw_current, "quarantine_categories": list(checks),
    }


# COMMAND ----------

# MAGIC %md ## Run

# COMMAND ----------

SUMMARY_COLS = [("run_id", "string"), ("run_at", "string"), ("source", "string"), ("contract_version", "string"),
                ("kind", "string"), ("rule_id", "string"), ("rule_name", "string"), ("severity", "string"),
                ("owner", "string"), ("rows_affected", "int"), ("rows_in", "int"),
                ("expected_initial", "int"), ("vs_profiling", "string")]


def save_sql(cfg, src, stmts):
    if not cfg.get("validation", {}).get("save_generated_sql", True):
        return
    out = Path(cfg["environment"]["landing_root"]) / "_generated_sql"
    out.mkdir(parents=True, exist_ok=True)
    parts = [f"-- {name}\nCREATE OR REPLACE TEMPORARY VIEW {name} AS\n{sql};" for name, sql in stmts["views"]]
    parts += [f"-- validated table\n{stmts['validated']};", f"-- quarantine table\n{stmts['quarantine']};"]
    if stmts["issues"]:
        parts.append(f"-- issues table\n{stmts['issues']};")
    (out / f"validate_{src}.sql").write_text("\n\n".join(parts) + "\n")


def validate_source(contract, cfg, d, run_id, run_at) -> list:
    c = contract["contract"]
    src, version = c["name"], str(c["version"])
    targets = {k: d.table(v) for k, v in contract["targets"].items()}
    stmts = build_statements(contract, cfg, d, run_id)
    save_sql(cfg, src, stmts)

    if not d.table_exists(stmts["raw_current"]):
        raise RuntimeError(f"{stmts['raw_current']} not found. Run Stage 2 (02_load_raw) first.")

    for name, sql in stmts["views"]:
        if SHOW_SQL:
            print(f"\n-- {name}\n{sql}")
        d.create_temp_view(name, sql)

    # Safety check BEFORE replacing anything.
    n = d.query(stmts["counts"])[0]
    rows_in, quarantined = int(n["rows_in"] or 0), int(n["quarantined"] or 0)
    max_share = cfg.get("validation", {}).get("max_quarantine_share", 0.05)
    if rows_in == 0:
        raise RuntimeError(f"{src}: the latest Raw load has no rows. Validated tables left unchanged.")
    if quarantined / rows_in > max_share:
        raise RuntimeError(
            f"{src}: {quarantined} of {rows_in} rows ({quarantined / rows_in:.1%}) would be quarantined, above the "
            f"limit of {max_share:.0%}. This usually means a systemic problem. Validated tables left unchanged. "
            f"Inspect view {stmts['views'][2][0]} (column quarantine_reasons) to see why.")

    d.create_or_replace_table(targets["validated"], stmts["validated"])
    d.create_or_replace_table(targets["quarantine"], stmts["quarantine"])
    if stmts["issues"]:
        d.create_or_replace_table(targets["issues"], stmts["issues"])

    # Reconciliation AFTER writing.
    n_valid = int(d.query(f"SELECT COUNT(*) AS n FROM {targets['validated']}")[0]["n"])
    n_quar = int(d.query(f"SELECT COUNT(*) AS n FROM {targets['quarantine']}")[0]["n"])
    if n_valid + n_quar != rows_in:
        raise RuntimeError(f"{src}: reconciliation failed: {rows_in} in, {n_valid} validated + {n_quar} quarantined.")

    base = {"run_id": run_id, "run_at": run_at, "source": src, "contract_version": version, "rows_in": rows_in}
    summary = [dict(base, kind="total", rule_id="ROWS_VALIDATED", rule_name="rows_validated", rows_affected=n_valid),
               dict(base, kind="total", rule_id="ROWS_QUARANTINED", rule_name="rows_quarantined", rows_affected=n_quar)]
    for cat in stmts["quarantine_categories"]:
        summary.append(dict(base, kind="quarantine", rule_id=f"Q-{cat.upper()}", rule_name=cat,
                            severity="quarantine", rows_affected=int(n[f"q_{cat}"] or 0)))
    if stmts["flag_counts"]:
        fc = d.query(stmts["flag_counts"])[0]
        for r in contract.get("flag_rules", []):
            hits = int(fc[f"flag_{r['name']}"] or 0)
            exp = r.get("expected_initial")
            summary.append(dict(base, kind="flag", rule_id=r["id"], rule_name=r["name"], severity=r["severity"],
                                owner=r["owner"], rows_affected=hits, expected_initial=exp,
                                vs_profiling="n/a" if exp is None else ("same" if exp == hits else "DIFFERENT")))
    return summary


def run_validate(config_path: str = CONFIG_PATH, dialect=None) -> list:
    cfg = load_config(config_path)
    contracts = load_contracts(cfg["_contracts_dir"])
    d = dialect or SparkDialect(cfg)
    run_id, run_at = str(uuid.uuid4()), datetime.now(timezone.utc).isoformat()
    summary = []
    for src in load_order(contracts):
        summary += validate_source(contracts[src], cfg, d, run_id, run_at)  # stops the run if a source fails
    d.append_rows(d.table("ops_dq_run_summary"), SUMMARY_COLS, summary)
    return summary


def print_summary(summary: list):
    for src in dict.fromkeys(s["source"] for s in summary):
        rows = [s for s in summary if s["source"] == src]
        tot = {s["rule_id"]: s["rows_affected"] for s in rows if s["kind"] == "total"}
        print(f"\n=== {src}: {rows[0]['rows_in']} in -> {tot['ROWS_VALIDATED']} validated, "
              f"{tot['ROWS_QUARANTINED']} quarantined (contract v{rows[0]['contract_version']})")
        q_hits = [s for s in rows if s["kind"] == "quarantine" and s["rows_affected"]]
        for s in q_hits:
            print(f"  QUARANTINE  {s['rule_name']:<16} {s['rows_affected']:>6}")
        for s in rows:
            if s["kind"] == "flag":
                note = "" if s["vs_profiling"] in ("same", "n/a") else f"   <-- profiling found {s['expected_initial']}"
                print(f"  {s['severity'].upper():<8} {s['rule_id']} {s['rule_name']:<30} {s['rows_affected']:>6}{note}")


# COMMAND ----------

if __name__ == "__main__" or ON_DATABRICKS:
    result = run_validate()
    print_summary(result)
