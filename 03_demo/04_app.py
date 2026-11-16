# Databricks notebook source
# MAGIC %md
# MAGIC # 04 · The app: Cloudstruck
# MAGIC
# MAGIC The CFO Office uses the solution through a Databricks App, `ifc-cfo-intelligence` (FastAPI + React). Its code is
# MAGIC in `03_demo/app/`: `backend/` (API, Genie, both agents, trust checks) and `frontend/dist` (the built React pages).
# MAGIC
# MAGIC | Page | What it shows |
# MAGIC |---|---|
# MAGIC | Overview | What is going well, what needs attention, and the ask bar (Genie) |
# MAGIC | Portfolio analytics | Investment by region, product and year; Genie answers with their SQL |
# MAGIC | Risk & exposure | Performance status, Category A exposure, expected credit loss |
# MAGIC | Client intelligence | Client 360°, comparison, Board recommendation, and both agents |
# MAGIC | Early warning | Clients with warning signals, by priority |
# MAGIC | Monthly review | Month-over-month changes across deliveries |
# MAGIC | Board briefing | One brief: strengths, downside scenarios, allocation view, human review queue |
# MAGIC
# MAGIC Walkthrough and demo script: `03_demo/README.md`. Setup and grants: `03_demo/app/README.md`.
# MAGIC Run this notebook to see the app's status and link; set `deploy` = yes to deploy the code in `03_demo/app`.

# COMMAND ----------

dbutils.widgets.dropdown("deploy", "no", ["no", "yes"], "Deploy 03_demo/app now")  # noqa: F821
APP_NAME = "ifc-cfo-intelligence"

# COMMAND ----------

from databricks.sdk import WorkspaceClient  # noqa: E402
from databricks.sdk.service.apps import AppDeployment  # noqa: E402

w = WorkspaceClient()
nb = dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()  # noqa: F821
source = (nb if nb.startswith("/Workspace") else "/Workspace" + nb).rsplit("/", 1)[0] + "/app"

if dbutils.widgets.get("deploy") == "yes":  # noqa: F821
    if w.apps.get(APP_NAME).compute_status.state.value != "ACTIVE":
        w.apps.start_and_wait(APP_NAME)
    d = w.apps.deploy_and_wait(APP_NAME, AppDeployment(source_code_path=source))
    print(f"Deployed from {source}: {d.status.state.value} · {d.status.message}")

app = w.apps.get(APP_NAME)
displayHTML(f"""<p><b>{APP_NAME}</b>: {app.app_status.state.value if app.app_status else '?'} ·
  compute {app.compute_status.state.value if app.compute_status else '?'}<br>
  Source: {app.active_deployment.source_code_path if app.active_deployment else '-'}<br>
  <a href="{app.url}" target="_blank">Open the app</a></p>""")  # noqa: F821
