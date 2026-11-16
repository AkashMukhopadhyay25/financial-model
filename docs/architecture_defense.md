# Architecture defense: request trace, failure scenarios, tradeoffs, pilot to scale

Preparation for the finalist presentation's technical Q&A (criterion 7) and the forward-deployed mindset criterion (5).
The architecture itself is in `README.md` §3 and `assets/architecture_diagram_agentic_solution.png`.

## 1. Tracing one request end to end

**Question:** a CFO analyst asks the stress-test agent: *"If all Active projects rated 5 or 6 default, how much more
would we need to set aside?"*

| # | Step | Component | What happens | Time |
|---|---|---|---|---|
| 1 | Ask | React page (Client intelligence → Stress-test agent) | Sends the question and the last turns of the conversation | – |
| 2 | Receive | FastAPI in the Databricks App | Runs as the app's service principal: least privilege, read access to `workspace.portfolio` | ms |
| 3 | Plan | Agent core → Foundation Model API (`databricks-qwen3-next-80b-a3b-instruct`) | The model receives the instructions and the tool definitions, and replies with a tool call: `run_stress_scenario(min_rating=5)` | ~2 s |
| 4 | Validate | `stress.py` | Parameters are checked (loss rate 0–1, known region names, rating 1–6); an invalid call returns an error message the model must fix | ms |
| 5 | Compute | SQL warehouse → `certified_investment_portfolio` | One deterministic SQL statement: baseline ECL $7,596M → stressed $16,427M (+$8,831M), with the breakdown and the 10 largest contributors | ~1–2 s |
| 6 | Explain | Foundation Model API | The model writes the answer in a fixed structure (answer, drivers, assumptions, caveats), copying figures from the tool result | ~2 s |
| 7 | Check | Agent core | Every number in the answer is matched against the tool results; any figure that cannot be traced is listed and the answer turns Amber. High-severity data issues among the shocked projects also make it Amber. | ms |
| 8 | Log | `ops_agent_runs` + MLflow | Question, answer, every tool call with its SQL, trust level, model and latency; the same run is an MLflow trace (AGENT → CHAT_MODEL and TOOL spans) in `/Shared/cloudstruck_agents` | ms |
| 9 | Show | React page | Baseline vs stressed ECL, drivers, projects (click opens the project record), the agent's steps with SQL, trust level. One click sends it to the Credit Risk Committee queue (`ops_review_requests`). | total **~5 s** |

A Genie question follows the same shape:
- Genie writes the SQL;
- the app (not Genie) counts the flagged projects in scope and sets the trust level;
- the app matches the question to a certified answer when one exists.

## 2. Failure and risk scenarios

| Scenario | What the system does | Where |
|---|---|---|
| **A delivery's columns change** (added, removed or renamed column) | The schema gate stops before reading any value; the file moves to `held/`; the job fails on purpose so the failure email goes out; nothing downstream changes | `01_schema_gate`, contracts |
| **Bad values in a file** | Unusable rows are quarantined with the reason; questionable rows are kept and flagged with an owner. If more than 5% would be quarantined, the run stops without replacing any table. | `03_validate` |
| **The same file is loaded twice** | Skipped by its SHA-256 fingerprint | `01_schema_gate` |
| **A correction arrives for a past month** | The new upload becomes active for that month and the old one is kept in Raw, marked superseded; only that month is rebuilt | monthly pipeline |
| **The figures don't reconcile across layers** | Blocking checks fail the job (raw = validated + quarantined = certified, for rows and every amount) | `06_dq_checks` |
| **The language model writes a number it didn't get from SQL** | The figure check lists the untraced figure and the answer turns Amber. In model testing this caught Llama 3.3 misquoting figures. | `agent_core.untraced_figures` |
| **The model picks the wrong scenario or region** | Invalid parameters are rejected with the valid values. For allocation, the decision rule runs in code before the model, and a consistency check turns the answer Amber if it prioritises a concentrated region. "North Africa" is resolved to its countries. | `stress.py`, `allocation_agent.consistency_checks` |
| **The model endpoint is down** | The agent returns Red: "No answer was produced". Every other page works, because they never depend on the model. | `agent_core.run` |
| **The SQL warehouse is down** | Pages show a clear error; cached pages keep working for up to 10 minutes; agents return Red ("no data tool returned a result") rather than guessing | `queries.cached`, `agent_core` |
| **Genie writes wrong or unexpected SQL** | The SQL is shown; the app computes the data-quality caveat itself; questions that match a certified answer show the certified figure; failed phrasings are added to the Genie space as examples | `trust.py`, Genie phrasing sheet |
| **Prompt injection, e.g. through a project description** | The agents never read free-text descriptions; their tools return numbers and names from certified tables. Text enrichment writes only to typed columns, and disagreements go to a person. | tool design, `04_enrich` |
| **Two people show the Board different figures** | One definition per measure in `ref_assumptions`; the two figures most often confused (Category A vs portfolio ECL) are always labelled; the Board briefing is generated from the same tables | A01–A24 |
| **Someone overrides a recommendation** | Recommendations are advice (`requires_human_review = true`). The Committee's decision is recorded with name and time; history is append-only. | review queue |
| **Stale data after a pipeline run** | Page cache lifetime is 10 minutes and it is cleared whenever a review is recorded; the header shows when the data was last refreshed | `queries.CACHE_TTL` |

## 3. Design choices and the alternatives we rejected

| Choice | Alternative considered | Why we chose this |
|---|---|---|
| Two narrow agents on one shared core | One general agent | Fewer tools per agent means more reliable tool choice with an open-weight model; each agent is tested on its own; the shared core keeps the guardrails in one place |
| Our agents next to Genie | Genie alone | The brief requires an agent of our own. Genie answers "what happened?"; what-if and allocation advice need fixed engines and stated rules. |
| The model never computes figures | Let the model calculate | Calculation in SQL makes the same question give the same number every time, which is the client's first requirement |
| Open-weight model hosted in Databricks (qwen3-next-80b) | Llama 3.3 70B, gpt-oss-120b | Tested on the same questions: fastest (~5 s) with every figure traced; Llama added filters nobody asked for. Data never leaves Databricks. The model is one setting. |
| Curated, dated research table | Live web search by the agent | Every market claim cited and reviewable before the Board sees it; no unvetted sources; it superseded an out-of-date WTO outlook during the build |
| Flag questionable rows, quarantine only unusable ones | Drop every row with an issue | Dropping rows silently changes totals; flags keep figures complete and doubts visible, with an owner |
| Join on `project_url` | Join on Project Number | Project Number is not unique: joining on it turns 3,768 monitoring records into 6,477 |
| FastAPI + React Databricks App | Streamlit | The user's mockups needed a multi-page product with drawers, tooltips and print layout; the app still runs inside Databricks with a service principal |
| 10-minute page cache | Always query live | Board briefing load fell from 11.5 s to about 1 s; the certified tables change only when the pipeline runs |
| Deterministic narrative (Monthly review, Board briefing) | Model-written summaries | Same data, same words; no risk of a hallucinated sentence in a Board pack |

## 4. Pilot to scale

| Phase | Duration | Scope | Exit criteria |
|---|---|---|---|
| **0. Prototype** (done) | 3 weeks | Synthetic data; WS1–WS3; two agents; app | Brief covered; 72/72 checks; 24/24 consistency |
| **1. Pilot** | 6–8 weeks | Real monthly deliveries from both teams; two champion analysts; one monthly pack in parallel with the old process | Figures match the manual pack; time to pack < 3 days; no Red answers left unexplained |
| **2. First Board cycle** | 1 quarter | Board risk pack built from the Board briefing; Credit Risk Committee works the review queue | Pack time cut from weeks to days; follow-up questions answered in the meeting |
| **3. Scale** | 2 quarters | More users and teams; SSO groups (analyst, committee, data owner); the monthly schedule of the pipeline job unpaused; the evaluation job as a required CI gate (job, Asset Bundle and MLflow tracing already exist); IFC's own probability-of-default and loss-given-default models in place of the 60% rule; more agents on the same core (Board-prep, figure reconciliation) | Consistency stays at 100%; cost per answer measured and accepted |

**What changes for production, honestly:**
- the data is synthetic and the ECL model is the brief's simplification;
- "review overdue" is derived, because no last-review date exists;
- the research is paraphrased and must be checked against the full reports;
- Genie's consistency is checked by a person today;
- the model's wording can be imprecise even when every figure is right.

## 5. How it scales

| Growth | Effect | Handled by |
|---|---|---|
| 10× more projects | Certified tables grow to ~50,000 rows | Delta tables and a serverless warehouse aggregate this in seconds; queries are already set-based |
| 100 concurrent users | More page views and questions | 10-minute page cache; serverless warehouse auto-scales; the app can add instances |
| More months of history | `certified_investment_portfolio_history` grows by one snapshot a month | Only changed months are rebuilt; trends read pre-computed KPI tables |
| New questions or agents | New tools and prompts | Add a deterministic function and a prompt; the core supplies tracing, trust levels and the audit log; rerun the evaluation |
| New data sources | New contracts | Add a contract; the schema gate and validation are driven by it |
