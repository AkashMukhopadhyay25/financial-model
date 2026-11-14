# Databricks notebook source
# MAGIC %md
# MAGIC # 03_build_agent — build, test, evaluate, log and deploy the CFO Decision Advisor
# MAGIC
# MAGIC ```
# MAGIC CFO / analyst ──► CFO Decision Advisor (cfo_agent.py, tool-calling LLM)
# MAGIC                     ├─► UC functions (governed SQL)  ──► gold_client_scorecard / gold_portfolio
# MAGIC                     ├─► Genie space (ad-hoc analytics, SQL shown) ──► gold tables
# MAGIC                     └─► trust layer: evidence footer + review status + agent_audit_log
# MAGIC ```
# MAGIC Prerequisites: `01_data/01_load_and_prepare`, `04_answers/ws2`, `04_answers/ws3` and `02_agent/02_agent_capabilities` have run;
# MAGIC `SQL_WAREHOUSE_ID` and `GENIE_SPACE_ID` are set in `00_config`.

# COMMAND ----------

# MAGIC %pip install -U -qqq "mlflow[databricks]>=3.1" databricks-sdk openai databricks-agents

# COMMAND ----------

dbutils.library.restartPython()

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

import importlib, os, sys
os.environ.update({
    "IFC_CATALOG": CATALOG, "IFC_SCHEMA": SCHEMA, "IFC_WAREHOUSE_ID": SQL_WAREHOUSE_ID,
    "IFC_GENIE_SPACE_ID": GENIE_SPACE_ID, "IFC_LLM_ENDPOINT": LLM_ENDPOINT,
})
assert SQL_WAREHOUSE_ID, "Set SQL_WAREHOUSE_ID in 00_config"
# cfo_agent.py sits next to this notebook. Some serverless workspaces cannot read workspace files that sit next to the
# running notebook (OSError: [Errno 5] Input/output error); then fetch the file through the Workspace API instead.
AGENT_FILE = os.path.join(os.getcwd(), "cfo_agent.py")
try:
    with open(AGENT_FILE) as _f:
        _f.read(1)
except OSError:
    import base64, tempfile
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.workspace import ExportFormat
    _nb_dir = os.path.dirname(dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get())
    _src = WorkspaceClient().workspace.export(f"{_nb_dir}/cfo_agent.py", format=ExportFormat.AUTO).content
    AGENT_FILE = os.path.join(tempfile.mkdtemp(), "cfo_agent.py")
    with open(AGENT_FILE, "wb") as _f:
        _f.write(base64.b64decode(_src))
    print(f"Read cfo_agent.py through the Workspace API -> {AGENT_FILE}")
sys.path.insert(0, os.path.dirname(AGENT_FILE))
import cfo_agent
importlib.reload(cfo_agent)

import mlflow
mlflow.set_experiment(f"/Users/{spark.sql('SELECT current_user()').first()[0]}/cfo_decision_advisor")
agent = cfo_agent.CFODecisionAdvisor()

def ask(q: str):
    r = agent.predict({"input": [{"role": "user", "content": q}]})
    print(r.output[0].content[0]["text"] if isinstance(r.output[0].content[0], dict) else r.output[0].content[0].text)
    print("\nreview:", r.custom_outputs["review_status"])
    return r

# COMMAND ----------

# MAGIC %md
# MAGIC ## Demo questions: the business user's journey
# MAGIC Each answer ends with its evidence trail and review status. The MLflow trace (in the cell output) shows every step.

# COMMAND ----------

_ = ask("Which clients should the Board be most concerned about, and how much exposure is affected?")

# COMMAND ----------

_ = ask("Why is the first client on that list flagged? Show me the evidence.")

# COMMAND ----------

_ = ask("Which Category A projects are Past Due or on the Watchlist, and how much should we set aside for potential losses?")

# COMMAND ----------

_ = ask("If we cancelled half of the undisbursed commitments to our most distressed client, what would our exposure be?")

# COMMAND ----------

_ = ask("Which two clients should we continue to invest in, and why?")

# COMMAND ----------

_ = ask("What was total approved investment in Sub-Saharan Africa last year?")   # routed to Genie

# COMMAND ----------

_ = ask("How do you define committed investment, and can I trust the region figures?")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Evaluation: does the agent give the submitted, validated figures?
# MAGIC The evaluation set comes from the WS2/WS3 answers (ground truth computed by governed SQL and reconciled independently).
# MAGIC Checks: (1) the expected figures appear in the answer, (2) every answer has an evidence trail, (3) decision questions
# MAGIC are flagged for human review, (4) out-of-scope questions are declined rather than invented.

# COMMAND ----------

import re
ws2 = spark.sql("SELECT * FROM board_risk_exposure() WHERE performance_status = 'TOTAL'").first().asDict()
recs = spark.table("ws3_recommendations").toPandas()

def fmt_variants(x):
    x = float(x)
    return {f"{x:,.0f}", f"{x:,.1f}", f"{x:,.2f}", f"{x:.0f}", f"{x:.2f}"}

EVAL = [
    {"q": "How much disbursed capital is tied up in Category A projects that are Past Due or on the Watchlist?",
     "expect": [ws2["disbursed_musd"]], "decision": False},
    {"q": "What expected credit loss should IFC provision for Category A Past Due projects?",
     "expect": [ws2["expected_credit_loss_musd"]], "decision": False},
]
for _, r in recs.iterrows():
    EVAL.append({"q": f"What is our total exposure affected for {r.client_name}, including undisbursed commitments?",
                 "expect": [r.exposure_affected_musd], "decision": False})
    EVAL.append({"q": f"Should we continue investing in {r.client_name}?", "expect": [], "decision": True})
EVAL.append({"q": "What will IFC's share price be next year?", "expect": [], "decision": False, "out_of_scope": True})

rows = []
for case in EVAL:
    r = agent.predict({"input": [{"role": "user", "content": case["q"]}]})
    text = r.output[0].content[0]["text"] if isinstance(r.output[0].content[0], dict) else r.output[0].content[0].text
    nums_ok = all(any(v in text for v in fmt_variants(e)) for e in case["expect"])
    has_trail = "How this answer was produced" in text
    review_ok = (r.custom_outputs["review_status"] == "HUMAN_REVIEW_REQUIRED") if case["decision"] else True
    rows.append({"question": case["q"], "figures_correct": nums_ok, "evidence_trail": has_trail,
                 "review_flag_correct": review_ok, "review_status": r.custom_outputs["review_status"],
                 "tools": ", ".join(t["tool"] for t in r.custom_outputs["tool_trace"])})

import pandas as pd
ev = pd.DataFrame(rows)
display(ev)
summary = {c: round(ev[c].mean() * 100, 1) for c in ["figures_correct", "evidence_trail", "review_flag_correct"]}
print("Evaluation (% of cases):", summary)
with mlflow.start_run(run_name="agent_evaluation"):
    mlflow.log_metrics({f"pct_{k}": v for k, v in summary.items()})
    mlflow.log_table(ev, "evaluation_results.json")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Optional: LLM-judged quality with MLflow GenAI scorers
# MAGIC Adds groundedness and guideline checks. Results appear in the MLflow experiment's *Evaluations* tab.

# COMMAND ----------

try:
    from mlflow.genai.scorers import Guidelines, RelevanceToQuery
    data = [{"inputs": {"input": [{"role": "user", "content": c["q"]}]}} for c in EVAL]
    mlflow.genai.evaluate(
        data=data,
        predict_fn=lambda input: agent.predict({"input": input}),
        scorers=[RelevanceToQuery(),
                 Guidelines(name="no_invented_numbers",
                            guidelines="Every monetary figure must be attributed to a tool result; the answer must not speculate."),
                 Guidelines(name="decision_disclaimer",
                            guidelines="If the answer recommends an action on a client, it must state that it requires human or committee review.")])
except Exception as e:
    print(f"GenAI evaluation skipped: {type(e).__name__}: {e}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Log to MLflow, register in Unity Catalog, deploy
# MAGIC Declaring resources lets Databricks pass credentials to the served agent automatically (no tokens in code).
# MAGIC In Free Edition, model serving for custom agents may be unavailable; the Databricks App (`03_demo`) then runs the same
# MAGIC `cfo_agent.py` in-process, so the demo is unaffected.

# COMMAND ----------

from mlflow.models.resources import (DatabricksFunction, DatabricksGenieSpace, DatabricksServingEndpoint,
                                     DatabricksSQLWarehouse, DatabricksTable)
resources = [DatabricksServingEndpoint(endpoint_name=LLM_ENDPOINT), DatabricksSQLWarehouse(warehouse_id=SQL_WAREHOUSE_ID)]
resources += [DatabricksFunction(function_name=T(f)) for f in
              ["get_client_scorecard", "get_client_projects", "list_clients", "board_risk_exposure",
               "simulate_exposure_reduction", "get_assumptions", "data_quality_summary"]]
resources += [DatabricksTable(table_name=T(t)) for t in
              ["gold_portfolio", "gold_client_scorecard", "ref_assumptions", "dq_results", "agent_audit_log"]]
if GENIE_SPACE_ID:
    resources.append(DatabricksGenieSpace(genie_space_id=GENIE_SPACE_ID))

mlflow.set_registry_uri("databricks-uc")
with mlflow.start_run(run_name="log_cfo_decision_advisor"):
    info = mlflow.pyfunc.log_model(
        name="cfo_decision_advisor",
        python_model=AGENT_FILE,
        resources=resources,
        # httpx is required by the SDK's OpenAI client; serving containers do not include it by default
        pip_requirements=["mlflow>=3.1", "databricks-sdk>=0.60", "openai", "httpx"],
        input_example={"input": [{"role": "user", "content": "Which clients need attention?"}]},
        registered_model_name=UC_MODEL_NAME,
    )
print("Registered", UC_MODEL_NAME, "version", info.registered_model_version)

# COMMAND ----------

try:
    from databricks import agents
    deployment = agents.deploy(
        UC_MODEL_NAME, info.registered_model_version,
        environment_vars={"IFC_CATALOG": CATALOG, "IFC_SCHEMA": SCHEMA, "IFC_WAREHOUSE_ID": SQL_WAREHOUSE_ID,
                          "IFC_GENIE_SPACE_ID": GENIE_SPACE_ID, "IFC_LLM_ENDPOINT": LLM_ENDPOINT},
        tags={"project": "ifc_cfo_copilot"})
    print("Endpoint:", deployment.endpoint_name, "| Review App:", deployment.review_app_url)
except Exception as e:
    print(f"Deployment skipped ({type(e).__name__}: {e}). The app runs the agent in-process instead.")
