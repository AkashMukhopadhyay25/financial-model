# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Build the agents
# MAGIC
# MAGIC Both of our agents run on one shared core (`03_demo/app/backend/agent_core.py`); each is a specification:
# MAGIC a model, instructions, a list of governed tools and optional deterministic checks.
# MAGIC
# MAGIC | Part | Where | What it does |
# MAGIC |---|---|---|
# MAGIC | Model | `serving.agents.*` in the config; app resource `stress-agent-model` | Databricks-hosted open-weight model (`databricks-qwen3-next-80b-a3b-instruct`) |
# MAGIC | Tool loop | `agent_core.run` | The model picks tools; the tools run SQL on the certified tables; at most 6 steps |
# MAGIC | Figure tracing | `agent_core.untraced_figures` | Every number in the answer must appear in a tool result, or the answer is Amber |
# MAGIC | Checks | `allocation_agent.consistency_checks` | e.g. never prioritise a region over the 25% concentration limit |
# MAGIC | Audit and tracing | `ops_agent_runs`, MLflow experiment `/Shared/cloudstruck_agents` | Every run, its tool calls and its trust level |
# MAGIC | Evaluation | `evaluate.py`, job `cloudstruck_agent_evaluation` | Several phrasings of each question must give the same figures |
# MAGIC
# MAGIC The app imports the same modules, so what is built here is what the CFO Office uses.

# COMMAND ----------

# MAGIC %run ./agent_setup

# COMMAND ----------

dbutils.widgets.dropdown("run_example", "no", ["no", "yes"], "Ask each agent one question (calls the model)")  # noqa: F821
dbutils.widgets.dropdown("run_evaluation", "no", ["no", "yes"], "Run the full evaluation (24 phrasings)")  # noqa: F821

# COMMAND ----------

# MAGIC %md ## The two agent specifications

# COMMAND ----------

from app.backend import allocation_agent, stress_agent  # noqa: E402

for agent in (stress_agent, allocation_agent):
    s = agent.spec()
    print(f"=== {s.title} ===")
    print(f"model: {s.model} · max steps: {s.max_steps} · tools: {', '.join(t.name for t in s.tools)}")
    print(f"prefetched context: {[p[0] for p in s.prefetch] or 'none'} · extra checks: {'yes' if s.checks else 'no'}")
    print(s.instructions[:1200] + ("…" if len(s.instructions) > 1200 else ""))
    print()

# COMMAND ----------

# MAGIC %md ## Ask each agent one question (optional: set `run_example` = yes)

# COMMAND ----------

if dbutils.widgets.get("run_example") == "yes":  # noqa: F821
    for agent, question in [(stress_agent, "What happens to expected credit loss if all Watchlist projects default?"),
                            (allocation_agent, "Where should IFC prioritise new commitments next year?")]:
        out = agent.ask(question, user="03_build_agent")
        print(f"Q: {question}\nTrust: {out['trust']['level']} · {'; '.join(out['trust']['reasons'])}\n{out['answer']}\n")
else:
    print("Skipped (set run_example = yes).")

# COMMAND ----------

# MAGIC %md ## Evaluation: the latest results, or a new run (set `run_evaluation` = yes)

# COMMAND ----------

from app.backend import evaluate  # noqa: E402
from app.backend.queries import T, q  # noqa: E402

if dbutils.widgets.get("run_evaluation") == "yes":  # noqa: F821
    import uuid

    eid = uuid.uuid4().hex[:12]
    rows = evaluate.run_stress() + evaluate.run_allocation()
    evaluate.save(rows, eid)
    print(evaluate.report(rows, eid))
latest = q(f"SELECT agent, count(*) AS phrasings, count_if(passed) AS consistent, max(evaluated_at) AS evaluated_at "
           f"FROM {T('ops_agent_evaluation')} WHERE eval_id = (SELECT max_by(eval_id, evaluated_at) "
           f"FROM {T('ops_agent_evaluation')}) GROUP BY agent")
display(spark.createDataFrame(latest))  # noqa: F821
