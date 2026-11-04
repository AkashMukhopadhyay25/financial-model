# Implementation strategy: IFC CFO Office, Forward Deployed challenge

How to use the reference solution in `Workspace/Teams/ifc-cfo-copilot/` to build your team's real submission by **Sun Nov 15, 11:59 p.m. EST**.

> Status: everything here was written against the case data and checked independently outside Databricks. The control totals, join behaviour, data issues and WS2 figures were all reproduced from the raw CSVs. **None of it has been run inside Databricks yet.** Expect small fixes on the first run, especially in the LLM and agent cells, which depend on your workspace's endpoints.

---

## 1. The winning thesis (say it in the first 20 seconds)

> "IFC's CFO Office can't answer the Board quickly because project and monitoring data live apart and every analyst rebuilds the numbers.
> We built one governed data foundation on Databricks and two cooperating agents. Genie answers *what happened*; our CFO Decision Advisor answers *what should we do*.
> Every figure comes from governed SQL, is traceable, and is flagged for human review when it supports a decision.
> A three-week Board pack becomes a five-minute conversation, with the same number regardless of who asks."

## 2. Where the points are and how this design earns them

| Criterion (pts) | What judges look for | How the reference earns it |
|---|---|---|
| Enterprise problem & success (12) | Users, workflow, prioritised scope, measurable success | Persona: CFO Office analyst and Board. Success metrics: benchmark accuracy %, time-to-answer, % answers with an evidence trail, review-flag precision |
| Agentic prototype (25) | Working, accurate, traceable across WS1–3 | 30 WS1 answers in `answers_register`; WS2 reconciled independently; WS3 table; Advisor with tools, Genie, evaluation, app |
| Data quality (15) | Validated prep, definitions, awareness of issues | 8 documented findings; 30+ stored checks; control totals; issue log; 17 written assumptions |
| Architecture & governance (18) | Clear components, justified choices | Medallion layers + UC functions as the only decision path + grants + audit log + MLflow; responsibility table in README |
| Forward-deployed mindset (10) | Trade-offs, limitations, pilot → scale | Rules vs LLM trade-off; review loop; Free-Edition fallback; Lakeflow / Review App / AI Gateway roadmap |
| Business impact & communication (10) | Value case on stated assumptions; outcome-focused demo | Value model below; 3-minute demo script |
| Defense & Q&A (10) | Trace a request, failure handling | Request trace in README §2; failure-mode table in §6 |

## 3. Build order: from today (Fri Oct 30) to submission

| Dates | Goal | Done when |
|---|---|---|
| Oct 30–31 | **Data foundation.** Import the reference, upload the CSVs to the volume, run `00_config` and `01_data`. Fix anything that breaks. | All blocking DQ checks pass; `gold_portfolio` has 5,000 rows; control totals match |
| Nov 1–2 | **WS1 + text features.** Run `ws1`. Hand-check 20 random rows of `gold_project_text_features` and every `needs_review` row; add overrides. | 30 answers stored; each Challenge answer spot-checked; you can explain every assumption |
| Nov 3–4 | **WS2 + WS3.** Run both. Debate the four clients as a team, record the rationale and confirm the picks are robust. | Reconciliation cell prints OK; `ws3_recommendations` holds four rows with rationale |
| Nov 5–7 | **Agents.** Run `02_agent_capabilities`, build the Genie space, run Genie benchmarks, then `03_build_agent`. | Genie benchmark score recorded; Advisor answers the 7 demo questions; evaluation ≥ 90% figures correct |
| Nov 8–10 | **App + polish.** Deploy the app, apply grants, export the architecture PNG, finalise the README. | A business user can do the whole demo in the app |
| Nov 11–13 | **Red-team.** Questions about clients that don't exist, ambiguous questions, out-of-scope questions, a tool failure (pause the warehouse), prompt injection in a question. Fix whatever breaks. | Failure-mode table in §6 is demonstrably true |
| Nov 14 | **Video** (≤ 3 min, include the diagram) + optional external-research extension | Video emailed to bta@rotman.utoronto.ca |
| Nov 15 | Freeze. Re-run everything top to bottom in a clean schema to prove reproducibility. | Workspace locks with a working, documented solution |

**Shared workspace note:** when the official team workspace arrives, change `CATALOG` (and maybe `SCHEMA`) in `00_config` only. Everything else follows.

## 4. Team roles (four people)

| Role | Owns |
|---|---|
| Data lead | `01_data`, DQ checks, text-feature review, reconciliation |
| Analytics lead | WS1/WS2 answers, Genie space and benchmarks, assumption wording |
| AI lead | UC functions, `cfo_agent.py`, evaluation, MLflow, app |
| Strategy & story | WS3 judgment and rationale, value case, README narrative, video and deck, Q&A prep |

## 5. Value case (state assumptions explicitly; adjust them with your team)

| Driver | Assumption (labelled) | Annual value |
|---|---|---|
| Board exposure pack | 4 packs/yr × 3 weeks × 3 analysts → 1 day × 1 analyst | ~170 analyst-days saved |
| Ad-hoc Board and management questions | 40/month × 1.5 days → 15 minutes | ~700 analyst-days saved |
| Avoided reconciliation disputes | 2 incidents/qtr × 5 days × 4 people | ~160 days saved |
| Earlier action on distressed clients | Freezing undisbursed commitments of REDUCE clients one quarter earlier avoids X% of drawdowns | Quantify with the WS3 table: undisbursed $ on REDUCE clients × assumed avoidable share |
| Risk & trust | One number per measure, an audit trail, and review flags | Qualitative (governance, Board confidence) |

Multiply the days by a loaded analyst cost (state it) and compare with the run cost: warehouse, serving and LLM tokens, which are small at CFO-Office volume.

## 6. Failure modes to demonstrate in Q&A

| Scenario | What happens |
|---|---|
| Client name doesn't exist | Tool returns 0 rows → the agent says so; status HUMAN_REVIEW_REQUIRED (no guessing) |
| Question needs data we don't have (e.g. share price) | Declined; no tool fabricates; evaluation includes this case |
| Genie writes wrong SQL | SQL is shown; status REVIEW_RECOMMENDED; benchmarks track accuracy; decision figures never depend on Genie |
| LLM text extraction is wrong | Rule cross-check flags it; a reviewer override wins; the count of awaiting-review rows is shown in Q13/Q24/Q25 |
| Source file is malformed next month | Blocking DQ checks stop the pipeline before gold tables change |
| Warehouse or endpoint down | Tool error is surfaced in the answer and logged; nothing invented |
| Prompt injection ("ignore rules and…") | The LLM can only call fixed, parameterised functions with read-only grants; no free SQL execution path except Genie, which has read-only access |
| Two people ask differently | Same UC function → same number; this is a core requirement |

## 7. Three-minute video script

1. **0:00–0:20.** The problem and the before state: three weeks, conflicting figures.
2. **0:20–0:50.** Architecture diagram: data → governed tools → two agents → trust layer.
3. **0:50–1:10.** Data trust: the 475 broken rows, the Project Number trap, control totals, the DQ table.
4. **1:10–2:20.** App demo:
   - The Board risk view (WS2 numbers).
   - Ask: "Which clients should we worry about?"
   - Then: "Why this one? Show the evidence."
   - Then: "What if we cancel half their undisbursed commitments?"
   - Show the evidence footer and review badge.
   - Ask one Genie question with its SQL visible.
5. **2:20–2:45.** The four recommendations with exposure affected.
6. **2:45–3:00.** Value and the pilot → scale path.

## 8. Optional extension (counts toward the 25 prototype points)

**External research.** Add a small curated set of dated industry outlooks (for example IEA renewables, World Bank Global Economic Prospects, IFC sector notes) as PDFs in a volume. Index them with **Vector Search** and add a `search_industry_research` tool to the Advisor. Have it recommend one industry to prioritise and one to approach with caution, citing sources with dates, and say whether this changes the four-client picks.

## 9. What to verify first when you run it

1. `ai_query` works with your `LLM_ENDPOINT` (try one row first: set the `todo` CTE to `LIMIT 5`).
2. `DECLARE OR REPLACE VARIABLE` runs (serverless / DBR 14.1+). If not, hard-code 0.60 in the gold step.
3. The UC `RETURNS TABLE` functions compile. If a type mismatch appears, cast in the function body.
4. Tool calling works on your chosen endpoint. Llama 3.3 70B and Claude endpoints support it.
5. In Free Edition, if `agents.deploy` is unavailable, the app runs the agent in-process; that's expected.
