"""
Deterministic trust check for an answer's SQL (MERGE_PLAN phase 8.3).

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
    """(where_sql or 'TRUE', None) if the query reads only the certified portfolio table; else (None, reason)."""
    try:
        tree = sqlglot.parse_one(sql, read="databricks")
    except Exception:
        return None, "The SQL could not be parsed for an automatic data-quality check."
    tables = {t.name.lower() for t in tree.find_all(exp.Table)}
    if tables != {PORTFOLIO}:
        return None, f"The SQL reads {', '.join(sorted(tables)) or 'no table'}; the automatic check covers only {PORTFOLIO}."
    if not isinstance(tree, exp.Select) or tree.find(exp.Join) or tree.args.get("with") \
            or any(s is not tree for s in tree.find_all(exp.Select)):
        return None, "The SQL uses joins, CTEs or subqueries; the automatic data-quality check needs a single-table query."
    where = tree.args.get("where")
    return (where.this.sql("databricks") if where else "TRUE"), None


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
            reasons.append(f"{counts['rows_text_review']:,} projects in scope have text-derived attributes awaiting review.")
    if not has_rows:
        reasons.append("The query returned no rows.")
    if counts is None or counts["rows_high_severity"] > 0:
        level, color = "REVIEW_RECOMMENDED", "amber"
    else:
        level, color = "VALIDATED", "green"
    return {"level": level, "color": color, "counts": counts, "reasons": reasons}
