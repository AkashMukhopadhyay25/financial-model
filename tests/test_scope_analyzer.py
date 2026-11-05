"""Unit tests for 02_agent/scope_analyzer.py: one case per SQL pattern Genie produced in the evaluation.

Run:  python tests/test_scope_analyzer.py   (or pytest tests/)
On Databricks the same patterns were checked against the certified answers: 10 of 10 scopes matched exactly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "02_agent"))
from scope_analyzer import scope_condition  # noqa: E402

T = "ifc_challenge.portfolio.certified_investment_portfolio"


def test_project_list_is_exact():
    cond, method = scope_condition(f"SELECT project_url, x FROM {T} WHERE a = 1 LIMIT 10",
                                   ["project_url", "x"], [["u1", 1], ["u2", 2]], T)
    assert method == "exact (project list)" and cond == "project_url IN ('u1', 'u2')"


def test_simple_where():
    cond, method = scope_condition(f"SELECT industry, sum(x) FROM {T} WHERE status <> 'Dropped' GROUP BY industry",
                                   ["industry", "s"], [["Energy", 1]], T)
    assert method == "filters (all branches)" and "status <> 'Dropped'" in cond


def test_union_branches_are_combined_and_lookup_subquery_ignored():
    sql = f"""WITH base AS (SELECT region, status, amt FROM {T}
                            WHERE approval_date > add_months((SELECT max(reporting_date) FROM {T}), -60))
              SELECT region, sum(amt) FROM base GROUP BY region
              UNION ALL SELECT region, sum(amt) FROM base WHERE status <> 'Dropped' GROUP BY region"""
    cond, method = scope_condition(sql, ["region", "s"], [["X", 1]], T)
    assert method == "filters (all branches)"
    assert "approval_date >" in cond and cond.count("SELECT") == 1   # the max() lookup stays inside, not OR-ed in


def test_having_restricts_to_result_groups():
    sql = f"SELECT country, sum(amt_loan_musd) FROM {T} WHERE status IN ('Active', 'Closed') GROUP BY country HAVING sum(amt_loan_musd) > 1000"
    cond, method = scope_condition(sql, ["country", "loan"], [["Brazil", 1200.0], ["India", 1100.0]], T)
    assert method == "filters + result groups" and "IN ('Brazil', 'India')" in cond


def test_limit_without_group_keys_is_not_guessed():
    sql = f"SELECT sum(x) AS s FROM (SELECT x FROM {T} ORDER BY x DESC LIMIT 10)"
    cond, method = scope_condition(sql, ["s"], [[5]], T)
    assert cond is None and method.startswith("not analysable")


def test_other_tables_are_not_guessed():
    sql = f"SELECT c.region, count(*) FROM {T} c JOIN ifc_challenge.portfolio.ops_dq_issues i ON c.project_url = i.project_url GROUP BY 1"
    cond, method = scope_condition(sql, ["region", "n"], [["X", 1]], T)
    assert cond is None and "ops_dq_issues" in method


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print("ok  ", t.__name__)
    print(f"{len(tests)} tests passed")
