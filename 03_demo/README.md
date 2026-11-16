# Demo: Cloudstruck from a business user's point of view

The demo is the Databricks App **`ifc-cfo-intelligence`** (Compute → Apps → ifc-cfo-intelligence → open the URL). It runs
on the certified tables in `workspace.portfolio`; no setup is needed beyond `README.md` §5.

## Walkthrough (about 10 minutes, for a live session)

1. **Overview: the portfolio at a glance, balanced.**
   - The headline cards: $742.6B approved across 5,000 projects (all statuses, A03), 1,233 Active, 399 clients.
   - **What is going well:**
     - 79% of Active projects are performing;
     - 95% of closed projects were completed;
     - 900 climate projects;
     - 87.6 GW of new renewable capacity;
     - 523 small-business finance projects;
     - FY2025 was a record year at $70.4B.
   - **Credit risk at a glance:** Category A expected credit loss of $3.31B, with the whole-portfolio figure of $7.60B
     next to it. The two are labelled, so nobody presents one as the other.
   - **Project spotlight:** switch between Largest Active, Strong performers, Recently approved and Needs attention.
     Click a project to see:
     - its lifecycle timeline;
     - disbursed against approved;
     - every data-quality flag in plain words, with its owner;
     - the description and the client's other projects.
2. **Ask Genie a question** in the blue box, e.g. *"Which Category A projects are Past Due or on the Watchlist?"* Show
   three things under the answer:
   - the SQL Genie wrote;
   - the trust level (Green / Amber / Red) and how many projects in scope carry data-quality flags, both computed by
     the app, not by Genie;
   - the match to the certified answer.
3. **Risk & exposure (WS2).** The two Board questions:
   - 95 projects, 61 clients, $15,473.36M approved, $11,447.52M disbursed, $3,311.72M provision;
   - for context, 298 of 393 Active Category A projects are performing.

   Open **Methodology** and **Evidence / SQL**.
4. **Client intelligence (WS3).** Step 4, **Board recommendation**: the four clients and their exposure affected. Then
   use the two agents at the top of the page:
   - **Stress-test agent:** ask *"If all Active projects rated 5 or 6 default, how much more would we need to set
     aside?"*
     - Answer: +$8,831M.
     - Bricor Finance and Wenhargal Renewables, our two reduce/review clients, are among the top drivers.
     - Open **How the agent worked** to see each tool call and its SQL.
     - Follow up with *"and at a 75% loss rate?"*
   - **Capital allocation agent:** ask *"Which industry should IFC prioritise, and does this change our four-client
     recommendation?"*
     - Answer: prioritise Energy, be cautious on Finance, limit Sub-Saharan Africa (27.8%, above the 25% limit).
     - Each market claim cites a dated source.
     - The two continue clients hold, on condition.
   - Click **Send to Credit Risk Committee** on either answer.
5. **Early warning.**
   - 215 clients with risk signals, ranked: 42 high priority.
   - 136 of the 351 clients with Active projects show no signal.
   - Mark a client as reviewed, or escalate it.
6. **Monthly review.** What changed from September to October in the demo months: who deteriorated, who improved,
   what went well, recommended next steps.
7. **Board briefing.** The Board pack in one page:
   - strengths;
   - Category A risk;
   - downside scenarios;
   - where new commitments should go;
   - the four clients, with the concentration condition;
   - early warning;
   - data quality.

   At the bottom is the **human review queue**: the item sent in step 4 is there; **Mark reviewed** records a decision.
   Finish with **Print / save as PDF**.
