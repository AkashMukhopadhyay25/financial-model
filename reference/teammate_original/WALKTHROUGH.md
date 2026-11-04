# Walkthrough: how the solution works, how to run it, how to ask it questions

Everything below is live in the Databricks workspace (`dbc-83823297-5832`) under
**Workspace → Users → ritvik.kohli@rotman.utoronto.ca → ifc-cfo-copilot**.

---

## 1. The story in one paragraph

IFC's CFO Office can't answer the Board quickly because project records and monitoring records live apart, and every
analyst rebuilds the numbers in spreadsheets. We built:
- **one governed data foundation** that joins and validates the two files;
- **a set of approved SQL "tools"** that compute every decision figure the same way every time;
- **two agents** on top:
  - **Genie** answers *"what happened?"* questions;
  - our **CFO Decision Advisor** answers *"so what should we do?"*.

Every answer shows the SQL behind it and a review status. Recommendations are always labelled
*human review required*, because they are advice to the Credit Risk Committee, not decisions.

---

## 2. What happens, layer by layer

```
CSV files ─► bronze ─► silver ─► text features ─► gold ─► UC functions ─► Genie / CFO Decision Advisor ─► you
 (volume)   (as-is)   (clean,     (LLM + rules,     (1 row per          (approved     (answers with evidence
                       flagged)    cross-checked)    project / client)   SQL tools)     + review status)
```

| Layer | Table(s) | What it does | Why a judge cares |
|---|---|---|---|
| Raw | volume `raw_files` | The two CSVs exactly as delivered | Reproducible; lineage starts at the file |
| Bronze | `bronze_projects`, `bronze_monitoring` | Lossless load. 475 descriptions span several lines, so a multi-line CSV reader is needed | Proves nothing was lost: row counts and **control totals match the source to the cent** |
| Silver | `silver_projects`, `silver_monitoring` | Types, trimming, region labels fixed, every anomaly flagged per row | Data quality is visible, not hidden |
| Reference | `ref_assumptions` (A01–A17), `ref_region_mapping`, `ref_product_vocabulary`, `ref_text_feature_overrides` | Business definitions as data | Genie, the agent and the README all quote the **same** definitions |
| Text features | `llm_text_extractions`, `rule_text_features`, `gold_project_text_features` | Llama 3.3 70B reads every description once; deterministic rules check it; disagreements go to a human | Answers the four [Challenge] questions consistently and traceably |
| Gold | `gold_portfolio` (5,000 rows), `gold_client_scorecard` (399 clients) | The two tables everything reads from; every column has a description | Small, documented surface for AI |
| Evidence | `dq_results`, `dq_issue_log`, `answers_register`, `ws3_recommendations`, `agent_audit_log` | Every check, answer, recommendation and agent reply is stored | The traceability requirement, met literally |
| Tools | 7 UC functions (`list_clients`, `get_client_scorecard`, `get_client_projects`, `board_risk_exposure`, `simulate_exposure_reduction`, `get_assumptions`, `data_quality_summary`) | Pre-approved SQL with typed parameters | **The LLM never writes the SQL behind a decision** |
| Agents | Genie space + `cfo_agent.py` (MLflow ResponsesAgent) | Genie = analyst; Advisor = plans, calls tools, explains, flags for review | The "agentic" part, with governance |

### Key findings worth saying out loud
1. **Project Number is not a key.** There are only 3,559 distinct values across 5,000 projects, so we join on Project Url.
2. **475 multi-line descriptions** break naive CSV loaders, including the Databricks upload UI.
3. **43 region labels** aren't in the data dictionary. They're restated, and the original label is kept.
4. **37 projects** were signed before approval, and **16** were invested with no signing date. Both are excluded from timing averages.
5. **146 projects** have a Board total that differs from their product split by more than $1M. This is reported (Q28), not silently fixed.
6. **31 projects** have empty descriptions.
7. **The LLM is not trusted blindly.** On the first run it labelled 228 projects as MSME financing where the rules did not. A manual review found it right on 112 (bank lending to "small firms / small companies") and wrong on 116 (farms, factories, corporate-only lending). Both lessons are now encoded. The rules and the LLM agree on the remaining text features.

### The verified numbers
| Question | Answer |
|---|---|
| WS2 Q1 | **95** Category A projects are Past Due (35) or Watchlist (60), across 61 clients, **$15,473M** approved |
| WS2 Q2 | **$11,448M** disbursed is tied up in them ($5,520M Past Due + $5,928M Watchlist); provision **$3,312M** (60% × Past Due disbursed) |
| WS3 Continue | **Rosar Telecom Holdings** ($3,141M affected, rating 1.62/6, 0% distressed); **Zansorzen Renewables** ($2,833M, 1.41/6, 0%) |
| WS3 Reduce / review | **Wenhargal Renewables** ($3,966M, 8 Past Due, 71% distressed, $853M ECL); **Bricor Finance Group** ($3,817M, 4 Past Due + 6 Watchlist, 77% distressed, $536M ECL) |
| Agent evaluation | 100% figures correct, 100% with evidence trail, 100% review flags correct (11 cases) |

WS2 figures were reproduced independently from the raw CSVs outside Databricks.

---

## 3. How to run it (from scratch, in order)

Open each notebook and click **Run all** (top right). Serverless compute starts automatically.

| # | Notebook | Takes | What you should see |
|---|---|---|---|
| 1 | `00_setup/00_config` | 30 s | `Config loaded: ifc_challenge.portfolio ...` |
| 2 | `01_data/01_load_and_prepare` | 3 min (≈60 min on a brand-new schema, because of the one-off LLM extraction) | All cells green; the last table shows Closed 1302 / Active 1233 / Pending 1233 / Dropped 1232 |
| 3 | `04_answers/ws1/ws1_answers` | 3 min | 35 answers with tables and two charts (Q27 bubble, Q30 heatmap) |
| 4 | `04_answers/ws2/ws2_board_questions` | 1 min | The Board tables, plus `OK` lines from the reconciliation |
| 5 | `04_answers/ws3/ws3_client_recommendations` | 1 min | Shortlists, robustness check, evidence per client, and a Board memo printed at the end |
| 6 | `02_agent/02_agent_capabilities` | 1 min | UC functions created; smoke-test tables |
| 7 | `02_agent/03_build_agent` | 6 min | 7 demo Q&As, evaluation = 100%, model registered, endpoint + Review App links |

You only need to re-run step 2 when new data arrives. Re-runs only send new or changed descriptions to the LLM.

**Where to change things:** only in `00_setup/00_config` (catalog, LLM endpoint, warehouse ID, Genie space ID, batch sizes).

---

## 4. How to ask it questions (three ways)

### A. Genie: quick factual questions
**Genie Agents → "Gold Portfolio Insights and Reference Assumptions Summa…"** (rename it to *IFC Portfolio Analyst* via
the title). Type a question and press Enter. Genie shows its SQL; click it to see exactly how the number was computed.

Try:
- *What was total approved investment by region last year?*
- *Which 10 countries have the most Active projects?*
- *How much new renewable generation capacity (MW) do Active and Closed projects have, by region?*
- *Show the loan vs equity split for East Asia & Pacific, excluding Dropped projects.*

### B. The CFO Decision Advisor: decisions, with evidence
**Option 1, the Review App** (a ready-made chat page; share it with teammates or judges). It is live at:
https://dbc-83823297-5832.cloud.databricks.com/ml/review-v2/7e64b9e2728b4f208839f17754ce805d/chat?o=7474644744293258
(also printed at the bottom of `03_build_agent`). The endpoint `agents_ifc_challenge-portfolio-cfo_decision_advisor`
must show **Ready** under *Serving*; a deployment takes ~15 minutes. Reviewers can rate each answer (Yes / No / I don't
know), and the ratings are stored for evaluation.

Verified live: *"If we cancelled half of Bricor Finance Group's undisbursed commitments, what would our exposure be?"*
returns $3,816.67M → $3,201.75M (−$614.93M), 🟢 VALIDATED, via `simulate_exposure_reduction`.

**Option 2, AI Playground:** **Playground** → choose the endpoint `agents_ifc_challenge-portfolio-cfo_decision_advisor`
→ chat.

**Option 3, in a notebook:** in `03_build_agent`, edit any cell such as `_ = ask("your question")` and run it.

Try this sequence (it is also the video demo script):
1. *Which clients should the Board be most concerned about, and how much exposure is affected?*
2. *Why is Bricor Finance Group flagged? Show me the evidence.*
3. *If we cancelled half of Bricor's undisbursed commitments, what would our exposure be?*
4. *Which two clients should we continue to invest in, and why?*
5. *Which Category A projects are Past Due or on the Watchlist, and what should we provision?*
6. *How do you define committed investment, and can I trust the region figures?*
7. *What will IFC's share price be next year?* (It should decline: there is no such data, and it won't invent any.)

**How to read an answer:**
- The answer itself comes first.
- Then **Review status**:
  - 🟢 `VALIDATED`: all figures come from approved functions.
  - 🟡 `REVIEW_RECOMMENDED`: figures come from Genie-generated SQL.
  - 🔴 `HUMAN_REVIEW_REQUIRED`: the answer contains a recommendation, or something failed.
- Then **How this answer was produced**: every tool called, with its SQL.
- Every answer is also stored in `agent_audit_log`, with the question, the answer, the tools used, the user and the latency.

---

## 5. How to defend it in Q&A (one line each)

- **"Why not let the LLM write SQL?"** Decision figures must be identical however the question is phrased; approved
  functions guarantee that, and Genie handles everything else with visible SQL.
- **"How do you know the data is right?"** Thirty-plus checks run on every load. Control totals match the source exactly,
  and the Board figures were reproduced independently.
- **"How do you know the LLM is right?"** We don't assume it is. Every extraction is cross-checked against rules,
  disagreements go to a human, and we showed a case where the review changed the logic (MSME).
- **"What happens when something fails?"** The tool error is shown, the answer is marked *human review required*, nothing
  is invented, and the failure is logged.
- **"How does this scale?"** Lakeflow pipeline + scheduled Job; Review App feedback; AI Gateway guardrails; row-level
  security by department; IFRS 9 PD/LGD in place of the flat 60%.

---

## 6. Still to do before Nov 15
- Export `assets/architecture_diagram_agentic_solution.mmd` to PNG (paste it into mermaid.live, then export).
- Optional: deploy the Streamlit app (`03_demo/04_app.py`; README §3, step 7).
- Optional: add Genie benchmarks from `genie_benchmark` and record the score.
- Optional extension: external industry research via Vector Search (strategy doc §8).
- Record the ≤3-minute video using the question sequence in §4B and email it to bta@rotman.utoronto.ca.
- When the official team workspace arrives: re-import the folder, change `CATALOG` in `00_config`, and run steps 1–7.
