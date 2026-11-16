"""
Capital Allocation Agent: "Where should IFC put new money, and where should it be careful?"

Tools (deterministic SQL in allocation.py / stress.py, curated research in ref_market_outlook):
  rank_segments              A23 ranking of industries / regions / industry x region on four credit metrics
  get_market_outlook         A24 curated, cited, dated external research (no live web)
  clients_in_segment         client scorecards (A15 bands) inside a segment
  get_board_recommendations  the WS3 four-client recommendation, to check whether the allocation view changes it
  segment_downside           what a segment would cost if its Watchlist projects defaulted (A11 via the stress engine)
  get_assumptions            governed definitions (A09, A11, A15, A23, A24, ...)
"""
import re

from . import agent_core, allocation, stress
from .settings import get_settings

SEG = {
    "industry": {"type": "string", "enum": [""] + stress.INDUSTRIES, "description": "Industry filter; empty for all."},
    "region": {"type": "string", "enum": [""] + stress.REGIONS,
               "description": "Region filter; empty for all. Africa = 'Sub-Saharan Africa'."},
}

INSTRUCTIONS = """You are the Capital Allocation Agent for IFC's CFO Office. You advise where IFC should prioritise NEW
commitments and where it should be cautious, combining two views that you keep separate:
  (a) our own track record: the A23 ranking from the certified portfolio (rank_segments), and
  (b) the market view: curated, cited, dated research (get_market_outlook).

How you work:
1. The allocation summary (the A23 decision rule applied by code), the industry and region rankings, the market outlook
   and the four-client recommendation (with each client's ranks and flags) are already in the conversation as tool
   results: base your answer on them. Your **Recommendation** sentence must state the summary's prioritise_industry,
   caution_industry, regions_to_grow and regions_to_limit exactly; you explain the choice, you do not change it. Call
   rank_segments(dimension="industry_region") when the user asks for finer detail.
2. Always say whether your view changes the four-client recommendation (two clients to continue, two to reduce or
   review), client by client, using the ranks and flags attached to each client. Call clients_in_segment for the prioritised segment if the user wants client names, and
   segment_downside for a cautioned segment if the user asks about downside.
3. Never compute, estimate or invent a figure or a rank. Copy every number from a tool result in this conversation
   (you may round it). Shares are returned as fractions: 0.201 means 20.1%.
4. Cite every market claim as [S#] with publisher and publication date, e.g. "[S3] IEA, June 2025". Use only the
   outlook rows you received; never cite anything else. If the data view and the market view disagree, say so plainly.
5. Name a segment or client only if it appears in a tool result. Amounts are USD millions: write $1,234M.
   Describe ranks exactly as returned ("4th of 5"), never as "highest" or "worst" unless the rank is the last one.
   Do not describe a metric with an adjective (low, strong, high) unless its rank on that metric is in the top two
   (low / strong) or bottom two (high / weak) of the segments shown.
6. Consistency rules:
   - Never recommend prioritising a region that is concentration-flagged or ranked in the bottom half, even if a market
     source is positive about it: say instead that the opportunity exists but new commitments there need offsetting. If the industry
     you prioritise is mostly held through clients in such a region, say new commitments in that industry should go to
     better-ranked regions or be offset by reductions elsewhere.
   - For each of the four clients, use the ranks, concentration flag and stances attached to it by
     get_board_recommendations. If a CONTINUE client sits in a concentration-flagged region, say that continuing adds
     to that concentration and suggest a condition (e.g. no net increase in that region's share).
   - Do not draw conclusions a source does not state: report its finding, cite it, and label your own inference as such.
7. Answer in this structure, concise, in markdown:
   **Recommendation**: one sentence from the allocation summary: prioritise <industry> (growing in <regions_to_grow>),
   approach <caution industry> with caution, and limit new exposure in <regions_to_limit>.
   **Our portfolio's evidence (A23)**: 2-4 bullets with the ranks and metrics behind the choice; mention any
   concentration flag.
   **Market view (A24)**: 2-3 bullets with citations.
   **Effect on the four-client recommendation**: one bullet per affected client, or say it holds.
   **Caveats**: the ranking uses past performance in synthetic data; outlooks are paraphrased summaries to verify before the
   Board; the decision rests with the Credit Risk Committee.
8. If a tool returns an error, fix the parameters and retry once; if it still fails, say so.
The reporting date is 2026-06-30."""


def _summary():
    return allocation.allocation_summary()


def _rank(dimension="industry", industry="", region=""):
    return allocation.rank_segments(dimension, industry, region)


def _outlook(industry="", region=""):
    return allocation.market_outlook(industry, region)


def _clients(industry="", region="", band="", limit=8):
    return allocation.clients_in_segment(industry, region, band, limit)


def _recs():
    return allocation.board_recommendations()


def _downside(industry="", region=""):
    return allocation.segment_downside(industry, region)


def _assumptions(ids=None):
    return stress.assumptions(ids or ["A23", "A24"])


TOOLS = [
    agent_core.Tool(
        "get_allocation_summary",
        "The A23 decision rule applied by code: industry to prioritise, industry to approach with caution, regions to grow, "
        "regions to limit (concentration-flagged or last), best industry x region segments outside them, and whether "
        "the market outlooks agree.",
        {}, _summary),
    agent_core.Tool(
        "rank_segments",
        "A23 ranking from the certified portfolio: per segment, Active projects, current exposure, portfolio share, "
        "distressed share, ECL rate, closed-project loss rate, exposure-weighted risk rating, undisbursed and unsigned "
        "pipeline, the four metric ranks, average and overall rank (1 = best), and a concentration flag.",
        {"dimension": {"type": "string", "enum": list(allocation.DIMENSIONS), "description": "Segment type."}, **SEG},
        _rank, ["dimension"]),
    agent_core.Tool(
        "get_market_outlook",
        "A24 curated external research: source_id (S#), publisher, title, publication date, URL, industry, region, stance "
        "(prioritise / neutral / caution) and finding. Filters keep rows for that industry/region plus the 'ALL' rows.",
        SEG, _outlook),
    agent_core.Tool(
        "clients_in_segment",
        "Client scorecards (A15 bands CONTINUE / MONITOR / REDUCE_OR_REVIEW) in a segment, largest exposure affected first.",
        {**SEG, "band": {"type": "string", "enum": ["", "CONTINUE", "MONITOR", "REDUCE_OR_REVIEW"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 15}},
        _clients),
    agent_core.Tool(
        "get_board_recommendations",
        "The WS3 four-client recommendation (two CONTINUE, two REDUCE_OR_REVIEW) with industry, region and exposure affected.",
        {}, _recs),
    agent_core.Tool(
        "segment_downside",
        "Downside for a segment: expected credit loss increase if its Watchlist projects defaulted (A11 loss rate), with the "
        "five clients contributing most.",
        SEG, _downside),
    agent_core.Tool(
        "get_assumptions",
        "Governed definitions, e.g. A23 allocation ranking, A24 external research, A11 ECL, A15 client bands.",
        {"ids": {"type": "array", "items": {"type": "string"}}}, _assumptions),
]


def consistency_checks(answer: str, results: list) -> list:
    """Deterministic: the recommendation must not prioritise a region that the A23 ranking flags as concentrated,
    and must cover the four-client recommendation."""
    problems = []
    flagged = set()
    for r in results:
        if r["tool"] == "rank_segments" and r["result"].get("dimension") == "region":
            flagged |= {x["region"] for x in r["result"]["rows"] if x.get("concentration_flag")}
    rec = next((ln for ln in answer.splitlines() if "recommendation" in ln.lower()), "")
    first_clause = re.split(r"caution|limit", rec.lower())[0]
    for g in flagged:
        if "priorit" in first_clause and g.lower() in first_clause:
            problems.append(f"the recommendation prioritises {g}, which is over the concentration limit (A23)")
    if not any(r["tool"] == "get_board_recommendations" for r in results):
        problems.append("the four-client recommendation was not checked (get_board_recommendations not called)")
    return problems


def spec() -> agent_core.AgentSpec:
    return agent_core.AgentSpec(name="capital_allocation", title="Capital Allocation Agent",
                                model=get_settings().allocation_agent_model, instructions=INSTRUCTIONS, tools=TOOLS,
                                max_steps=8, checks=consistency_checks,
                                prefetch=[("get_allocation_summary", {}),
                                          ("rank_segments", {"dimension": "industry"}),
                                          ("rank_segments", {"dimension": "region"}),
                                          ("get_market_outlook", {}), ("get_board_recommendations", {})])


def ask(question: str, history: list = None, user: str = "") -> dict:
    return agent_core.run(spec(), question, history, user)


PRESETS = [
    "Which industry should IFC prioritise for new commitments, and which should it approach with caution? Does this change our four-client recommendation?",
    "Where are we too concentrated, and what does the market outlook say about it?",
    "Is Energy still a good place to grow? Show the evidence and the healthiest clients we could grow with.",
    "What is the downside if Finance clients' Watchlist projects default, and does the market view support caution there?",
]
