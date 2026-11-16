"""
Reserve & Stress-Test Agent: "How much should IFC set aside if things get worse?"

Tools (all deterministic SQL in stress.py on certified_investment_portfolio / ref_assumptions):
  run_stress_scenario   baseline vs stressed expected credit loss for a what-if, with breakdown and worst projects
  get_risk_baseline     where current exposure, Past Due, Watchlist and ECL sit today (by region, industry, client, ...)
  get_assumptions       the governed definitions behind the figures (A09 exposure, A10 undisbursed, A11 ECL, ...)
"""
from . import agent_core, stress
from .settings import get_settings

FILTERS = {
    "region": {"type": "string", "enum": [""] + stress.REGIONS,
               "description": "Region filter, exact value. Africa = 'Sub-Saharan Africa'. North Africa (Egypt, Morocco, "
                              "Tunisia, Algeria, Libya) is inside 'Middle East': use the country filter for it."},
    "country": {"type": "string", "description": "Country filter: one name ('Kenya'), several separated by commas "
                                                  "('Egypt, Morocco'), or 'North Africa' (= Egypt, Morocco, Tunisia, "
                                                  "Algeria, Libya). Empty for all."},
    "industry": {"type": "string", "enum": [""] + stress.INDUSTRIES, "description": "Industry filter; empty for all."},
    "client": {"type": "string", "description": "Client ID (e.g. CL-0087) or part of the client name; empty for all."},
    "environmental_category": {"type": "string", "enum": ["", "A", "B", "C"],
                               "description": "Environmental and social category filter; empty for all."},
}
GROUP_BY = {"type": "string", "enum": list(stress.GROUP_COLUMNS),
            "description": "Dimension for the breakdown table."}

INSTRUCTIONS = """You are the Reserve & Stress-Test Agent for IFC's CFO Office. You help the CFO size reserves and
understand how much capital is at risk if credit conditions get worse. Genie answers descriptive portfolio questions;
your job is what-if analysis on expected credit loss (ECL).

How you work:
1. Translate the question into one or more scenarios and call run_stress_scenario for each. Typical mappings:
   - "Watchlist projects slip / turn Past Due" -> migrate_watchlist = true.
   - "high-risk / rated 5-6 projects default" -> min_rating = 5 ("rated 6" -> 6).
   - "loss severity / LGD of X%" -> loss_rate = X/100 (A11 uses 60%).
   - "clients draw down their remaining commitments" -> drawdown_share (e.g. 0.5 for half, 1 for all).
   - A place, sector or client -> the filters. Africa = region 'Sub-Saharan Africa'. North Africa = country
     'North Africa' (never region 'Middle East', which also holds Jordan, Syria, etc.).
   The stressed ECL is portfolio-wide. When you report a scenario, say how much of the increase comes from newly
   defaulted projects and how much from existing Past Due projects (loss-rate or drawdown change); the summary returns both.
   If the user asks to compare scenarios, run each one.
2. If the user asks where risk sits today, call get_risk_baseline. If asked how something is defined, call get_assumptions.
3. Never compute, estimate or invent a figure. Every number you write must be copied from a tool result in this
   conversation (you may round it, e.g. 10109.45 -> $10,109M). The tools already return the increases you need.
4. Never add facts that are not in the tool results: name a region, country, industry, client or project only if it
   appears in the breakdown or top_projects you received, and do not speculate about causes. The data-quality counts
   (shocked_projects_with_dq_issues) are open data-quality flags, not early-warning signals or credit events.
   Amounts are USD millions: write them like $10,109M.
5. Answer in this structure, concise, in markdown:
   **Answer**: one or two sentences with the stressed ECL and the increase over the baseline.
   **What drives it**: the largest contributors from the breakdown (2-4 bullets).
   **Assumptions**: the scenario assumptions as returned by the tool (short bullets).
   **Caveats**: data-quality counts from the summary; this is a what-if, not a forecast; reserves are decided by the
   Credit Risk Committee.
6. If a tool returns an error, fix the parameters and try again once; if it still fails, say so plainly.
The reporting date is 2026-06-30."""


def _scenario(migrate_watchlist=False, min_rating=0, loss_rate=None, drawdown_share=0.0, group_by="region",
              region="", country="", industry="", client="", environmental_category="", scenario_name="") -> dict:
    return stress.run_scenario(migrate_watchlist=migrate_watchlist, min_rating=min_rating, loss_rate=loss_rate,
                               drawdown_share=drawdown_share, group_by=group_by, region=region, country=country,
                               industry=industry, client=client, environmental_category=environmental_category,
                               name=scenario_name)


def _baseline(group_by="region", region="", country="", industry="", client="", environmental_category="") -> dict:
    return stress.risk_baseline(group_by, region, country, industry, client, environmental_category)


def _assumptions(ids=None) -> dict:
    return stress.assumptions(ids)


TOOLS = [
    agent_core.Tool(
        "run_stress_scenario",
        "Baseline vs stressed expected credit loss (USD millions) for a what-if on Active projects: which projects move "
        "to default, at what loss rate, with what drawdown of undisbursed commitments. Returns a summary, a breakdown "
        "and the 10 projects contributing most.",
        {"scenario_name": {"type": "string", "description": "Short label, e.g. 'Watchlist slips to default'."},
         "migrate_watchlist": {"type": "boolean", "description": "Watchlist projects move to default (Past Due)."},
         "min_rating": {"type": "integer", "minimum": 0, "maximum": 6,
                        "description": "Active projects with internal risk rating >= this move to default; 0 = off."},
         "loss_rate": {"type": "number", "description": "Share of the defaulted amount lost, 0-1. Omit to use A11 (0.6)."},
         "drawdown_share": {"type": "number",
                            "description": "Share (0-1) of the undisbursed commitment of defaulted projects assumed drawn "
                                           "before default. 0 = A11 as is."},
         "group_by": GROUP_BY, **FILTERS},
        _scenario),
    agent_core.Tool(
        "get_risk_baseline",
        "Where risk sits today on Active projects: exposure, Past Due and Watchlist counts, projects rated 5-6, "
        "Watchlist exposure, undisbursed commitments and baseline ECL, grouped by a dimension (top 15 by exposure).",
        {"group_by": GROUP_BY, **FILTERS}, _baseline),
    agent_core.Tool(
        "get_assumptions",
        "Governed definitions behind the figures, e.g. A09 current exposure, A10 undisbursed commitments, "
        "A11 expected credit loss, A15 client bands, A22 early-warning signals.",
        {"ids": {"type": "array", "items": {"type": "string"}, "description": "Assumption IDs, e.g. ['A11']."}},
        _assumptions),
]


def spec() -> agent_core.AgentSpec:
    return agent_core.AgentSpec(name="stress_test", title="Reserve & Stress-Test Agent",
                                model=get_settings().stress_agent_model, instructions=INSTRUCTIONS, tools=TOOLS)


def ask(question: str, history: list = None, user: str = "") -> dict:
    return agent_core.run(spec(), question, history, user)


# Ready-made scenarios for the UI (one click; the agent still runs them through its tools).
PRESETS = [
    "What happens to our expected credit loss if every Watchlist project slips to Past Due?",
    "If all Active projects rated 5 or 6 default, how much more would we need to set aside, and which clients drive it?",
    "Stress Sub-Saharan Africa: Watchlist projects default and clients draw half of their undisbursed commitments.",
    "How sensitive is the reserve to the loss rate? Compare 45%, 60% and 75% on today's Past Due projects.",
]
