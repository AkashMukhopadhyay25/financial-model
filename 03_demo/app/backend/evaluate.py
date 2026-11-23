"""
Paraphrase-consistency evaluation for the team's own agents (the client's first requirement: the same figures however
a question is phrased).

For each case, four phrasings are sent to the agent. The expected result is computed directly by the deterministic
engine (no language model). A phrasing passes when:
  stress test   the scenario the agent ran gives exactly the expected ECL increase, the answer quotes that figure,
                and the trust level is not Red;
  allocation    the answer's recommendation names the expected industries and regions in the right roles, and the
                deterministic consistency checks pass.
Results go to ops_agent_evaluation (one row per phrasing) and 02_agent/agent_evaluation_report.md.

Run from the repo root:  PYTHONPATH=03_demo python -m app.backend.evaluate
"""
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import agent_core, allocation, allocation_agent, stress, stress_agent
from .queries import T, q

STRESS_CASES = [
    {"case": "S1 Watchlist defaults", "params": {"migrate_watchlist": True}, "phrasings": [
        "What happens to our expected credit loss if every Watchlist project slips to Past Due?",
        "If all the Watchlist names go into default, how much bigger does the reserve get?",
        "Stress test: migrate the whole Watchlist to default. What's the ECL impact?",
        "How much more would we have to provision if every project currently on the Watchlist became Past Due?"]},
    {"case": "S2 Ratings 5-6 default", "params": {"min_rating": 5}, "phrasings": [
        "If all Active projects rated 5 or 6 default, how much more would we need to set aside?",
        "What is the additional expected loss if our highest-risk projects (internal rating 5 and 6) all default?",
        "Assume every Active project with a risk rating of 5 or worse goes into default. Impact on ECL?",
        "How big is the reserve hit if the projects rated 5-6 fail?"]},
    {"case": "S3 Africa Watchlist + half drawdown", "params": {"migrate_watchlist": True, "region": "Sub-Saharan Africa",
                                                              "drawdown_share": 0.5}, "phrasings": [
        "Stress Sub-Saharan Africa: Watchlist projects default and clients draw half of their undisbursed commitments.",
        "In Sub-Saharan Africa, what if the Watchlist projects default after drawing 50% of what is still undisbursed?",
        "Africa scenario: Watchlist goes Past Due and half of the undisbursed commitments get drawn first. ECL change?",
        "How much would expected credit loss rise if Sub-Saharan African Watchlist projects defaulted with a 50% drawdown?"]},
    {"case": "S4 Loss rate 75%", "params": {"loss_rate": 0.75}, "phrasings": [
        "What happens to the reserve on today's Past Due projects if the loss rate is 75% instead of 60%?",
        "If loss given default rises to 75%, how much more ECL do we need on the existing Past Due book?",
        "Recompute expected credit loss on current Past Due exposure at a 75% loss severity.",
        "How sensitive is the reserve: Past Due projects at 75% LGD rather than the 60% we assume?"]},
]

ALLOCATION_CASES = [
    {"case": "A1 Prioritise vs caution", "phrasings": [
        "Which industry should IFC prioritise for new commitments, and which should it approach with caution?",
        "Where should new money go by sector, and which sector should we be careful with?",
        "Give me the industry to grow and the industry to slow down on for new commitments.",
        "For the next round of commitments, which sector is the best bet and which is the riskiest?"]},
    {"case": "A2 Concentration", "phrasings": [
        "Where are we too concentrated, and what does the market outlook say about it?",
        "Which region is over our concentration limit, and should we keep adding there?",
        "Is any part of the portfolio too concentrated? What should we do about new commitments?",
        "Concentration check: which regions should we limit and where should we grow instead?"]},
]


def _figure_in(answer: str, value: float) -> bool:
    """True if the answer quotes value (USD millions) as a money figure, at any rounding the figure check accepts."""
    money = [m.group(0) for m in agent_core.NUM.finditer(answer)
             if m.group(0).strip().startswith("$") or re.search(r"[MB]$|billion$|million$", m.group(0).strip())]
    return any(not agent_core.untraced_figures(tok, [{"v": value}]) for tok in money)


def run_stress():
    rows = []
    for c in STRESS_CASES:
        expected = stress.run_scenario(**c["params"])["summary"]["ecl_increase_musd"]
        for i, ph in enumerate(c["phrasings"], 1):
            r = stress_agent.ask(ph, user="evaluation")
            ran = [x["result"]["summary"]["ecl_increase_musd"] for x in r["results"] if x["tool"] == "run_stress_scenario"]
            matched = any(abs(v - expected) < 0.01 for v in ran)
            quoted = _figure_in(r["answer"], expected)
            ok = matched and quoted and r["trust"]["level"] != "HUMAN_REVIEW_REQUIRED"
            rows.append({"agent": "stress_test", "case": c["case"], "phrasing_no": i, "question": ph,
                         "expected": f"ECL increase {expected:,.2f}", "observed": ", ".join(f"{v:,.2f}" for v in ran) or "no scenario run",
                         "scenario_matched": matched, "figure_quoted": quoted, "trust_level": r["trust"]["level"],
                         "passed": ok, "latency_ms": r["latency_ms"], "run_id": r["run_id"]})
            print(f"  {c['case']} #{i}: {'PASS' if ok else 'FAIL'} ran={ran} expected={expected} quoted={quoted} {r['trust']['level']}")
    return rows


def run_allocation():
    s = allocation.allocation_summary()
    exp = {"prioritise": s["prioritise_industry"], "caution": s["caution_industry"], "limit": s["regions_to_limit"]}
    rows = []
    for c in ALLOCATION_CASES:
        for i, ph in enumerate(c["phrasings"], 1):
            r = allocation_agent.ask(ph, user="evaluation")
            rec = next((ln for ln in r["answer"].splitlines() if "recommendation" in ln.lower()), "").lower()
            head, _, tail = rec.partition("caution")
            matched = (exp["prioritise"].lower() in head and exp["caution"].lower() in rec
                       and all(g.lower() in rec for g in exp["limit"]))
            checks_ok = not any("Consistency check" in x for x in r["trust"]["reasons"])
            ok = matched and checks_ok and r["trust"]["level"] != "HUMAN_REVIEW_REQUIRED"
            rows.append({"agent": "capital_allocation", "case": c["case"], "phrasing_no": i, "question": ph,
                         "expected": f"prioritise {exp['prioritise']}; caution {exp['caution']}; limit {', '.join(exp['limit'])}",
                         "observed": rec[:300], "scenario_matched": matched, "figure_quoted": checks_ok,
                         "trust_level": r["trust"]["level"], "passed": ok, "latency_ms": r["latency_ms"], "run_id": r["run_id"]})
            print(f"  {c['case']} #{i}: {'PASS' if ok else 'FAIL'} {r['trust']['level']} | {rec[:120]}")
    return rows


def save(rows, eval_id):
    q(f"""CREATE TABLE IF NOT EXISTS {T('ops_agent_evaluation')} (
  eval_id STRING, evaluated_at TIMESTAMP, agent STRING, case_name STRING, phrasing_no INT, question STRING,
  expected STRING, observed STRING, scenario_matched BOOLEAN, figure_quoted BOOLEAN, trust_level STRING,
  passed BOOLEAN, latency_ms BIGINT, run_id STRING)
COMMENT 'Paraphrase-consistency evaluation of the team''s agents: 4 phrasings per case, expected result from the deterministic engine.'""")
    for r in rows:
        q(f"""INSERT INTO {T('ops_agent_evaluation')} SELECT :e, now(), :a, :c, CAST(:n AS INT), :qq, :x, :o,
CAST(:m AS BOOLEAN), CAST(:f AS BOOLEAN), :t, CAST(:p AS BOOLEAN), CAST(:l AS BIGINT), :r""",
          {"e": eval_id, "a": r["agent"], "c": r["case"], "n": r["phrasing_no"], "qq": r["question"], "x": r["expected"],
           "o": r["observed"], "m": r["scenario_matched"], "f": r["figure_quoted"], "t": r["trust_level"],
           "p": r["passed"], "l": r["latency_ms"], "r": r["run_id"] or ""})


def report(rows, eval_id) -> str:
    lines = ["# Agent evaluation: paraphrase consistency", "",
             f"Run `{eval_id}` on {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC. Every row is also in `ops_agent_evaluation`.",
             "Expected results come from the deterministic engines, called directly (no language model).", ""]
    for agent in ("stress_test", "capital_allocation"):
        rs = [r for r in rows if r["agent"] == agent]
        if not rs:
            continue
        n = sum(r["passed"] for r in rs)
        lines += [f"## {agent.replace('_', ' ').title()}: {n} of {len(rs)} phrasings consistent", "",
                  "| Case | # | Question | Expected | Observed | Trust | Pass |", "|---|---|---|---|---|---|---|"]
        for r in rs:
            obs = r["observed"].replace("|", "/").replace("\n", " ")[:120]
            lines.append(f"| {r['case']} | {r['phrasing_no']} | {r['question']} | {r['expected']} | {obs} | {r['trust_level']} | "
                         f"{'yes' if r['passed'] else '**no**'} |")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    eid = uuid.uuid4().hex[:12]
    t0 = time.time()
    print("Stress-test agent"); rows = run_stress()
    print("Capital allocation agent"); rows += run_allocation()
    save(rows, eid)
    out = Path(__file__).resolve().parents[3] / "02_agent" / "agent_evaluation_report.md"  # 03_demo/app/backend -> repo
    out.parent.mkdir(exist_ok=True)
    out.write_text(report(rows, eid) + "\n")
    print(f"{sum(r['passed'] for r in rows)} of {len(rows)} passed in {time.time() - t0:.0f}s; report: {out}")
    print(json.dumps({"eval_id": eid}))
