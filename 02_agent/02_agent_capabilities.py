# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Agent capabilities
# MAGIC
# MAGIC Three capabilities answer the CFO Office's three questions. All of them read the same certified tables, so a
# MAGIC figure is the same wherever it is asked; together they feed one decision (the Board briefing in the app).
# MAGIC
# MAGIC | Capability | The question | How it answers |
# MAGIC |---|---|---|
# MAGIC | **Genie space** | What happened? | Plain language to SQL on `certified_investment_portfolio`, `ref_assumptions` and `ops_dq_issues`, with the 30 certified WS1 queries as examples. The app then counts the flagged projects in scope (trust check). |
# MAGIC | **Reserve & Stress-Test Agent** | What if credit worsens? | Deterministic scenario SQL (`stress.py`): baseline vs stressed expected credit loss. The model chooses the scenario and explains it; it never computes a figure. |
# MAGIC | **Capital Allocation Agent** | Where should new money go? | The A23 segment ranking and the decision rule in code (`allocation.py`), with cited market research (A24, `ref_market_outlook`). A consistency check blocks prioritising a concentrated region. |
# MAGIC
# MAGIC The cells below call each capability's tools directly, **without the language model**, to show what the agents
# MAGIC can see. `03_build_agent` shows how the agents are put together and evaluated.

# COMMAND ----------

# MAGIC %run ./agent_setup

# COMMAND ----------

# MAGIC %md ## Genie: the certified answers it is measured against

# COMMAND ----------

from app.backend.queries import T, q  # noqa: E402

display(spark.createDataFrame(q(  # noqa: F821
    f"SELECT question_id, question, row_count, rows_in_scope, rows_needing_review FROM {T('answers_register')} "
    "WHERE workstream = 'WS1' ORDER BY question_id")))

# COMMAND ----------

# MAGIC %md ## Stress-test agent: a downside scenario (Watchlist projects move to default at the A11 loss rate)

# COMMAND ----------

from app.backend import stress  # noqa: E402

r = stress.run_scenario(migrate_watchlist=True, group_by="region", name="Watchlist to default")
sm = r["summary"]
print(f"Expected credit loss: ${sm['ecl_baseline_musd']:,.2f}M today -> ${sm['ecl_stressed_musd']:,.2f}M "
      f"(+${sm['ecl_increase_musd']:,.2f}M) if {sm['shocked_projects']} Watchlist projects default.")
print("\n".join(r["assumptions"]))
display(spark.createDataFrame(r["breakdown"]))  # noqa: F821

# COMMAND ----------

# MAGIC %md ## Capital allocation agent: the A23 decision rule

# COMMAND ----------

from app.backend import allocation  # noqa: E402

for k, v in allocation.allocation_summary().items():
    print(f"{k}: {v}")

# COMMAND ----------

# MAGIC %md ## The tools each agent may call

# COMMAND ----------

from app.backend import allocation_agent, stress_agent  # noqa: E402

for agent in (stress_agent, allocation_agent):
    s = agent.spec()
    print(f"\n{s.title} (model: {s.model})")
    for t in s.tools:
        print(f"  - {t.name}: {t.description.split('. ')[0]}.")
