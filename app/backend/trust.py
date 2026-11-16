"""
Deterministic trust check for an answer's SQL.

Genie writes the SQL; this module, not Genie, decides the caveat. If the SQL reads only certified_investment_portfolio,
the projects in scope are counted with Genie's own WHERE clause, and the answer carries
"N of M projects in this answer have open data-quality issues (K high severity)".

Trust levels (colors the CFO Office uses):
  VALIDATED              Green  SQL analyzed; no high-severity data-quality issue in scope
  REVIEW_RECOMMENDED     Amber  high-severity issues in scope, or the SQL could not be analyzed automatically
  HUMAN_REVIEW_REQUIRED  Red    no SQL / no result, so nothing can be traced
Reasons are always listed.
"""
import sqlglot
from sqlglot import exp

PORTFOLIO = "certified_investment_portfolio"


def scope_where(sql: str):
    """(where_sql or 'TRUE', None) if the projects the query reads can be stated as one WHERE on the certified
    portfolio table; else (None, reason).

    Genie usually writes CTEs, derived tables or PIVOTs. Each SELECT that reads the portfolio table directly
    contributes its own WHERE; the scope is their OR (a branch with no WHERE reads every project). Outer layers
    (CTE consumers, PIVOT, window functions, ORDER BY / LIMIT) reshape those rows but read no other projects.
    This is the same definition as answers_register.scope_where for the certified answers."""
    try:
        tree = sqlglot.parse_one(sql, read="databricks")
    except Exception:
        return None, "The SQL could not be parsed for an automatic data-quality check."
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    reads = [t for t in tree.find_all(exp.Table) if t.name.lower() not in ctes]
    other = sorted({t.name.lower() for t in reads} - {PORTFOLIO})
    if other:
        return None, f"The SQL also reads {', '.join(other)}; the automatic check covers only {PORTFOLIO}."
    if not reads:
        return None, "The SQL reads no table, so there are no projects to check."

    wheres = []
    for t in reads:
        sel = t.parent.parent if isinstance(t.parent, exp.From) else None
        if not isinstance(sel, exp.Select) or (sel.args.get("joins") or sel.args.get("joins_")):
            # the table is joined (or used some other way): a join can change which rows are in scope
            if _in_condition(t):
                continue  # e.g. WHERE as_of_date = (SELECT max(as_of_date) FROM portfolio)
            return None, "The SQL joins the portfolio table, so its scope cannot be checked automatically."
        if _in_condition(sel):
            continue
        w = sel.args.get("where")
        if w is None:
            return "TRUE", None
        cond = w.this.copy()
        alias = (t.alias_or_name or "").lower()
        for col in cond.find_all(exp.Column):
            if col.table and col.table.lower() in (alias, PORTFOLIO):
                col.set("table", None)
                col.set("db", None)
                col.set("catalog", None)
        wheres.append(cond.sql("databricks"))
    wheres = list(dict.fromkeys(wheres))
    if not wheres:
        return None, "The SQL's scope could not be determined automatically."
    if len(wheres) == 1:
        return wheres[0], None
    return " OR ".join(f"({w})" for w in wheres), None


def _in_condition(node) -> bool:
    """True when node sits inside a WHERE or HAVING (e.g. a scalar subquery for the reporting date)."""
    p = node.parent
    while p is not None:
        if isinstance(p, (exp.Where, exp.Having)):
            return True
        p = p.parent
    return False


def assess(sql: str, has_rows: bool, db, table_fqn: str) -> dict:
    reasons, counts = [], None
    if not sql:
        return {"level": "HUMAN_REVIEW_REQUIRED", "color": "red", "counts": None,
                "reasons": ["No SQL was returned, so the answer cannot be traced to governed data."]}
    where, why = scope_where(sql)
    if where is None:
        reasons.append(why)
    else:
        try:
            r = db.query(f"""SELECT count(*) AS rows_in_scope, count_if(needs_review) AS rows_needing_review,
                                    count_if(dq_max_severity = 'high') AS rows_high_severity,
                                    count_if(text_attributes_need_review) AS rows_text_review
                             FROM {table_fqn} WHERE {where}""")[0]
            counts = {k: int(v or 0) for k, v in r.items()}
            counts["scope_where"] = where
        except Exception as e:  # e.g. Genie used a column alias inside WHERE
            reasons.append(f"The data-quality count could not be computed ({type(e).__name__}).")
    if counts:
        if counts["rows_needing_review"]:
            reasons.append(f"{counts['rows_needing_review']:,} of {counts['rows_in_scope']:,} projects in scope have open "
                           f"data-quality issues ({counts['rows_high_severity']:,} high severity). They are included, not excluded.")
        else:
            reasons.append(f"None of the {counts['rows_in_scope']:,} projects in scope has an open data-quality issue.")
        if counts["rows_text_review"]:
            n = counts["rows_text_review"]
            reasons.append(f"{n:,} project{'s' if n != 1 else ''} in scope {'have' if n != 1 else 'has'} text-derived attributes awaiting review.")
    if not has_rows:
        reasons.append("The query returned no rows.")
    if counts is None or counts["rows_high_severity"] > 0:
        level, color = "REVIEW_RECOMMENDED", "amber"
    else:
        level, color = "VALIDATED", "green"
    return {"level": level, "color": color, "counts": counts, "reasons": reasons}
