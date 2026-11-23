# Users, requirements and success criteria

## Who uses Cloudstruck, and how their work changes

| User | Today (from the brief) | With Cloudstruck |
|---|---|---|
| **CFO Office analyst** | Pulls the project and monitoring files from two teams, rebuilds the calculations in spreadsheets, reconciles them by hand for each request; an exposure summary takes about three weeks | Asks in plain language (Genie) or opens a certified answer; every figure carries its SQL, assumptions and data-quality count. Builds the Board pack from the Board briefing page. |
| **CFO** | Receives figures late, sometimes two versions of the same measure | One set of definitions (A01–A24) behind every page; the Overview balances what is going well against what needs attention; asks the agents "what if credit worsens?" and "where should new money go?" |
| **Board director** | Follow-up questions cannot be answered in the meeting | The Board briefing answers the standing questions; the analyst answers follow-ups live in Genie or the agents, with the figures traceable |
| **Credit Risk Committee** | Sees issues only when someone escalates them by email | A review queue: agents' answers, clients and projects arrive with their evidence; the Committee records a decision (append-only history) |
| **Data owners** (data team, portfolio monitoring, investment department, investment operations) | Errors surface when a figure is challenged | Each open data issue is routed to its owner with a plain-language message (`ops_dq_issues`); the Board briefing shows the load per team |

## Requirements, in priority order

| Priority | Requirement (source) | How Cloudstruck meets it | Status |
|---|---|---|---|
| **Must** | Consistent figures, whoever asks and however it is phrased (brief §2) | One certified table and 24 written assumptions used by every channel; agents compute nothing themselves; Category A vs portfolio ECL always labelled | Met: 24 of 24 agent phrasings identical; Genie sheet ready for a person to run |
| **Must** | Every answer traceable to source data and method (brief §2) | SQL shown with every page, Genie answer and agent step; assumption IDs on every certified answer; agent runs logged in `ops_agent_runs` | Met |
| **Must** | Flag answers that need human review before they are relied on (brief §2) | Green / Amber / Red trust level with reasons, computed by code; data-quality count in scope; review queue with recorded decisions | Met |
| **Must** | Data prepared, validated and combined in Databricks (brief §2, §4) | Contract-checked pipeline in Unity Catalog; join on `project_url`; 72 checks | Met: 72 of 72 checks pass |
| **Must** | WS1 30 questions with SQL; WS2 two Board questions; WS3 four-client recommendation (brief §4) | `answers_register`, `ws3_recommendations`, Board memo | Met |
| **Must** | At least one agent of our own alongside Genie (brief WS3) | Reserve & Stress-Test Agent and Capital Allocation Agent | Met |
| **Should** | State assumptions where data or questions are ambiguous (brief §4) | `ref_assumptions` A01–A24, shown in the app's Assumptions drawer | Met |
| **Should** | Interface for business users (optional extension) | Databricks App "Cloudstruck", seven pages | Met |
| **Should** | External research, cited and dated (optional extension) | `ref_market_outlook`: eight sources (IMF, World Bank, IEA, GSMA, WTO, FAO) | Met |
| **Could** | Month-on-month monitoring | Monthly review (demo months July–October 2026) | Met (demo data) |
| **Could** | Scheduled pipeline, MLflow tracing, SSO roles | Described in the pilot-to-scale plan | Next phase |

## Success criteria: target and measured result

| Criterion | Target | Measured (16 November 2026) |
|---|---|---|
| Time to answer a standard portfolio question | Minutes instead of weeks | Certified answer about **1 s**; cached pages under 0.1 s; Board briefing about **1 s** (cached, about 5 s cold) |
| Time to answer a what-if or allocation question | Under 30 s | Stress-test agent **4.9 s** on average (worst 5.5 s); capital-allocation agent **11.0 s** on average (worst 14.7 s) |
| Same figure however a question is phrased | 100% | **24 of 24** agent phrasings (`02_agent/agent_evaluation_report.md`); Genie: sheet of 32 phrasings ready (`02_agent/genie_phrasing_test.md`) |
| Every agent figure traceable to SQL | 100% of figures | Enforced by code: any untraced figure turns the answer Amber and is listed. In the evaluation, every figure traced. |
| Data reconciles across every layer | 0 unexplained differences | **72 of 72** data-quality checks pass (raw = validated + quarantined = certified, for rows and every amount); **14 of 14** WS1 reconciliation checks pass |
| Coverage of the brief | All three workstreams | WS1 **30 of 30** questions (36 certified answers incl. detail lists), WS2 **2 of 2**, WS3 recommendation, both optional extensions |
| Data issues visible and owned | Every flagged row has an owner | **1,260** projects flagged (78 high), routed to **4** owners; none excluded from figures |
| Human review recorded | Every escalation has a decision trail | Review queue with reviewer, time and decision; append-only |
| Agent answers that fail outright | Under 5% | **3 of 66** logged runs Red, all on 16 November before a missing library was added to the app; 0 since |
