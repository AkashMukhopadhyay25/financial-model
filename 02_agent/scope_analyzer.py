"""Which projects does a generated SQL answer cover?

Genie (or any text-to-SQL tool) writes its own SQL. To attach a data-quality caveat that does not depend on the model
remembering to add one, we work out deterministically which rows of the certified table the answer covers, then count
how many of those carry open data-quality flags.

`scope_condition(sql, result_columns, result_rows, table)` returns `(condition, method)`, where `condition` is a SQL
boolean expression on `table` selecting the covered projects, or `(None, reason)` when the scope cannot be determined.
Methods, tried in order:

1. **exact (project list)**: the result has a `project_url` column, so the covered projects are exactly those rows.
2. **filters (all branches)**: every SELECT that reads `table` as a row source (top level, CTE bodies, UNION branches,
   FROM subqueries) contributes its WHERE clause; branches are combined with OR. Subqueries used inside a filter
   (e.g. `(SELECT max(reporting_date) ...)`) are lookups, not row sources, and are skipped.
3. **filters + result groups**: if HAVING, LIMIT, QUALIFY or a window filter narrows the rows after the WHERE, the scope
   is further restricted to the GROUP BY values that appear in the result (e.g. only the countries returned).

Anything else (joins on the certified table, other tables) is reported as not analysable rather than guessed.
Pure Python (sqlglot); no Spark needed, so it is unit-tested locally in tests/test_scope_analyzer.py.
"""
import sqlglot
from sqlglot import exp


def _table_name(t: exp.Table) -> str:
    return ".".join(p for p in [t.catalog, t.db, t.name] if p).lower()


def _literal(v) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def _from(sel: exp.Select):
    return sel.args.get("from") or sel.args.get("from_")   # the key name differs between sqlglot versions


def _is_row_source(sel: exp.Select) -> bool:
    """True for SELECTs that produce the answer's rows; False for subqueries inside a filter or used as one value."""
    if sel.find_ancestor(exp.Where, exp.Having, exp.Qualify) is not None:
        return False
    node = sel
    while isinstance(node.parent, (exp.Subquery, exp.Paren)):
        node = node.parent
    return node.parent is None or isinstance(node.parent, (exp.From, exp.Join, exp.CTE, exp.Union, exp.With))


def scope_condition(sql: str, result_columns: list, result_rows: list, table: str):
    """Condition on `table` selecting the projects a query's answer covers, plus the method used.

    result_columns: column names of the query result; result_rows: rows as sequences or dicts (same order as columns).
    """
    table = table.lower()
    cols = [c.lower() for c in result_columns]
    rows = [[r.get(c) for c in result_columns] if isinstance(r, dict) else list(r) for r in result_rows]

    # 1. The result lists projects: exact.
    if "project_url" in cols:
        i = cols.index("project_url")
        urls = sorted({r[i] for r in rows if r[i]})
        if not urls:
            return "FALSE", "exact (project list, empty)"
        return "project_url IN (" + ", ".join(_literal(u) for u in urls) + ")", "exact (project list)"

    try:
        tree = sqlglot.parse_one(sql, read="databricks")
    except Exception as e:
        return None, f"not analysable (SQL could not be parsed: {type(e).__name__})"

    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    others = {_table_name(t) for t in tree.find_all(exp.Table)} - {table} - ctes
    if others:
        return None, f"not analysable (also reads {', '.join(sorted(others))})"

    # 2. Filters of every SELECT that reads the table as a row source.
    conditions, group_keys = [], set()
    for sel in tree.find_all(exp.Select):
        if not _is_row_source(sel):
            continue
        frm = _from(sel)
        if frm is None or not isinstance(frm.this, exp.Table) or _table_name(frm.this) != table:
            continue
        if sel.args.get("joins"):
            return None, "not analysable (join on the certified table)"
        where = sel.args.get("where")
        cond = where.this.copy() if where else exp.true()
        for col in cond.find_all(exp.Column):
            col.set("table", None)                      # the condition is applied to the table directly
        conditions.append(cond.sql(dialect="databricks"))
        group = sel.args.get("group")
        if group:
            group_keys |= {e.name.lower() for e in group.expressions if isinstance(e, exp.Column)}
    if not conditions:
        return None, "not analysable (the certified table is not a row source)"
    condition = "(" + ") OR (".join(conditions) + ")"

    # 3. Narrowing after the WHERE: keep only the groups present in the result.
    narrowed = any(s.args.get(k) for s in tree.find_all(exp.Select) for k in ("having", "limit", "qualify"))
    if not narrowed:
        return condition, "filters (all branches)"
    keys = [k for k in sorted(group_keys) if k in cols]
    if not keys:
        return None, "not analysable (HAVING/LIMIT without group keys in the result)"
    for k in keys:
        i = cols.index(k)
        values = sorted({str(r[i]) for r in rows if r[i] is not None})
        condition += f" AND CAST({k} AS STRING) IN (" + (", ".join(_literal(v) for v in values) or "NULL") + ")"
    return condition, "filters + result groups"
