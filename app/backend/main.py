"""
Bellwether (IFC CFO Office portfolio intelligence): FastAPI backend for the Databricks App.

  /api/*       JSON for the React frontend (every response carries its SQL evidence)
  /            the built React app (app/frontend/dist)

Run locally (DuckDB preview built from data/):
    uvicorn app.backend.main:app --reload            # from the repo root
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent_core, allocation_agent, genie, monthly, queries, stress_agent
from .settings import get_settings

log = logging.getLogger("ifc_app")
app = FastAPI(title="Bellwether", docs_url="/api/docs", openapi_url="/api/openapi.json")
DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@app.exception_handler(Exception)
async def _errors(request: Request, exc: Exception):
    log.exception("API error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"error": f"{type(exc).__name__}: {exc}"})


def _user(request: Request) -> str:
    """Databricks Apps forward the signed-in user's identity in these headers."""
    h = request.headers
    return h.get("x-forwarded-email") or h.get("x-forwarded-preferred-username") or h.get("x-forwarded-user") or "local-user"


@app.get("/api/health")
def health(request: Request):
    s = get_settings()
    return {"ok": True, "data_mode": s.data_mode, "catalog": s.catalog, "schema": s.schema,
            "warehouse_configured": bool(s.warehouse_id), "genie_configured": bool(s.genie_space_id),
            "user": _user(request)}


@app.get("/api/overview")
def overview():
    return queries.overview()


@app.get("/api/portfolio/options")
def portfolio_options():
    return queries.filter_options()


@app.get("/api/portfolio")
def portfolio(region: str = "", country: str = "", industry: str = "", department: str = "",
              product_line: str = "", status: str = "", year: str = ""):
    return queries.portfolio(dict(region=region, country=country, industry=industry, department=department,
                                  product_line=product_line, status=status, year=year))


@app.get("/api/answers")
def answers():
    return queries.answers_library()


@app.get("/api/answers/{question_id}")
def answer(question_id: str):
    a = queries.certified_answer(question_id)
    if not a:
        raise HTTPException(404, f"No certified answer {question_id}")
    return a


@app.get("/api/risk")
def risk():
    return queries.risk()


@app.get("/api/clients")
def clients(search: str = "", band: str = "", limit: int = 50):
    return queries.clients(search, band, min(limit, 400))


@app.get("/api/clients/recommendations")
def recommendations():
    return queries.recommendations()


@app.get("/api/clients/compare")
def compare(ids: str = ""):
    return queries.compare([i for i in ids.split(",") if i])


@app.get("/api/clients/{client_id}")
def client(client_id: str):
    c = queries.client_detail(client_id)
    if not c:
        raise HTTPException(404, f"Unknown client {client_id}")
    return c


@app.get("/api/early-warning")
def early_warning():
    return queries.early_warning()


@app.get("/api/briefing")
def briefing():
    return queries.briefing()


@app.get("/api/assumptions")
def assumptions():
    return queries.assumptions()


@app.get("/api/monthly/status")
def monthly_status():
    return monthly.status()


@app.get("/api/monthly/compare")
def monthly_compare(a: str, b: str, dimension: str = "Portfolio"):
    try:
        return monthly.compare(a, b, dimension)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/monthly/review")
def monthly_review(month: str = ""):
    return monthly.review(month)


@app.get("/api/monthly/client")
def monthly_client(name: str, month: str):
    if not monthly.MONTH_RE.match(month):
        raise HTTPException(400, "Month must look like 2026-10")
    return monthly.client_month(name, month)


@app.get("/api/monthly/series")
def monthly_series():
    return monthly.series()


@app.get("/api/monthly/changes")
def monthly_changes(a: str, b: str, change_type: str = ""):
    try:
        return monthly.changes(a, b, change_type)
    except ValueError as e:
        raise HTTPException(400, str(e))


class UploadFile64(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    content_base64: str


class MonthUpload(BaseModel):
    month: str
    files: list[UploadFile64]


@app.post("/api/monthly/upload")
def monthly_upload(body: MonthUpload):
    try:
        return monthly.upload(body.month, [f.model_dump() for f in body.files])
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/monthly/runs")
def monthly_runs():
    return monthly.runs()


class AskBody(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    conversation_id: Optional[str] = None


@app.post("/api/genie/ask")
def ask(body: AskBody, request: Request):
    question = body.question.strip()
    r = genie.ask(question, body.conversation_id)
    if r.get("available"):
        r["history_id"] = queries.save_genie_answer(question, r, _user(request))
    return r


@app.get("/api/genie/history")
def genie_history(limit: int = 100):
    return queries.genie_history(min(limit, 500))


@app.get("/api/genie/history/{history_id}")
def genie_history_item(history_id: str):
    item = queries.genie_history_item(history_id)
    if not item:
        raise HTTPException(404, "Not found in history")
    return item


class FeedbackBody(BaseModel):
    conversation_id: str
    message_id: str
    positive: bool


@app.post("/api/genie/feedback")
def feedback(body: FeedbackBody):
    return genie.send_feedback(body.conversation_id, body.message_id, body.positive)


# ---- the team's own agents (Genie answers "what happened?"; these answer "so what?")
class AgentAskBody(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list = Field(default_factory=list, max_length=12)  # earlier turns [{role, content}] for follow-ups


@app.get("/api/agents/stress-test")
def stress_agent_info():
    s = stress_agent.spec()
    return {"name": s.name, "title": s.title, "model": s.model, "presets": stress_agent.PRESETS,
            "tools": [{"name": t.name, "description": t.description} for t in s.tools]}


@app.post("/api/agents/stress-test/ask")
def stress_agent_ask(body: AgentAskBody, request: Request):
    return stress_agent.ask(body.question.strip(), body.history, _user(request))


@app.get("/api/agents/stress-test/runs")
def stress_agent_runs(limit: int = 20):
    return agent_core.recent_runs("stress_test", min(limit, 100))


@app.get("/api/agents/capital-allocation")
def allocation_agent_info():
    s = allocation_agent.spec()
    return {"name": s.name, "title": s.title, "model": s.model, "presets": allocation_agent.PRESETS,
            "tools": [{"name": t.name, "description": t.description} for t in s.tools]}


@app.post("/api/agents/capital-allocation/ask")
def allocation_agent_ask(body: AgentAskBody, request: Request):
    return allocation_agent.ask(body.question.strip(), body.history, _user(request))


@app.get("/api/agents/capital-allocation/runs")
def allocation_agent_runs(limit: int = 20):
    return agent_core.recent_runs("capital_allocation", min(limit, 100))


@app.get("/api/agents/runs/{run_id}")
def agent_run(run_id: str):
    r = agent_core.get_run(run_id)
    if not r:
        raise HTTPException(404, "Not found")
    return r


class ReviewBody(BaseModel):
    entity_type: str = Field(pattern="^(client|project|answer)$")
    entity_id: str = Field(min_length=1, max_length=500)
    entity_name: Optional[str] = Field(default=None, max_length=500)
    action: str = Field(pattern="^(flag_for_review|mark_reviewed)$")
    note: Optional[str] = Field(default=None, max_length=2000)
    source_page: Optional[str] = Field(default=None, max_length=100)


@app.post("/api/review-requests")
def add_review(body: ReviewBody, request: Request):
    return queries.add_review_request(body.model_dump(), _user(request))


@app.get("/api/review-requests")
def list_reviews():
    return queries.review_requests()


# ---- frontend (single-page app): serve built files, fall back to index.html for client-side routes
if DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        # index.html must never be cached, so a new deploy shows on a normal reload (assets are content-hashed)
        return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
