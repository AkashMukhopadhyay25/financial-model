"""CFO Decision Advisor: the team-built agent that works alongside Genie.

Genie answers "what happened?". This agent answers "so what should we do?". It plans, calls governed tools
(Unity Catalog functions, plus Genie for open-ended analytics), reasons over the results and returns an
explained answer with:
  * an evidence trail (every tool called and the exact SQL behind each figure), and
  * a review status: VALIDATED / REVIEW_RECOMMENDED / HUMAN_REVIEW_REQUIRED.

The same module is used by 02_agent/03_build_agent (testing, evaluation, MLflow logging and serving) and by the
Databricks App in 03_demo/04_app.py. Configuration comes from environment variables, so nothing is hard-coded.
"""
import json
import os
import re
import time
import uuid
from typing import Any

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import ResponsesAgentRequest, ResponsesAgentResponse

CATALOG = os.environ.get("IFC_CATALOG", "workspace")
SCHEMA = os.environ.get("IFC_SCHEMA", "cfo_copilot")
WAREHOUSE_ID = os.environ.get("IFC_WAREHOUSE_ID", "")
GENIE_SPACE_ID = os.environ.get("IFC_GENIE_SPACE_ID", "")
LLM_ENDPOINT = os.environ.get("IFC_LLM_ENDPOINT", "databricks-meta-llama-3-3-70b-instruct")
MAX_STEPS = 8
FQ = f"{CATALOG}.{SCHEMA}"

SYSTEM_PROMPT = f"""You are the CFO Decision Advisor for IFC's CFO Office. You help finance staff and the Board understand
portfolio exposure and decide which client relationships need attention.

Rules you must follow:
1. Never invent or estimate a number. Every figure in your answer must come from a tool result in this conversation.
2. For anything about a specific client, call get_client_scorecard and, when justifying a view, get_client_projects.
3. To find clients that stand out, call list_clients (REDUCE_OR_REVIEW for concerns, CONTINUE for strong relationships).
4. For the Board's Category A / Past Due / Watchlist question, call board_risk_exposure.
5. For other portfolio analytics (volumes, regions, products, timelines), call ask_genie with a precise question.
6. If asked how something is defined or calculated, call get_assumptions. If asked whether data can be trusted, call data_quality_summary.
7. Amounts are USD millions; write them like $1,234M. "Exposure affected" = current disbursed exposure + undisbursed commitments.
8. When you give a recommendation, use this structure: Recommendation; Exposure affected; Evidence (key metrics and the
   worst projects); Risks and uncertainties; Suggested next step. Recommendations are advice to the Credit Risk Committee,
   not decisions.
9. If a tool returns no rows or an error, say so plainly and do not guess.
10. Be concise: lead with the answer, then the evidence.
Data lives in Unity Catalog {FQ}; the reporting date is 2026-06-30."""


def _fn(name, description, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []}}}


TOOLS = [
    _fn("get_client_scorecard", "Exposure, credit risk, performance history and rule-based band for one client.",
        {"client": {"type": "string", "description": "Client ID (e.g. CL-0087) or part of the client name"}}, ["client"]),
    _fn("get_client_projects", "Project-level evidence for one client (status, performance, rating, exposure per project).",
        {"client": {"type": "string", "description": "Client ID or part of the client name"}}, ["client"]),
    _fn("list_clients", "Ranked shortlist of clients in a band: REDUCE_OR_REVIEW, CONTINUE, MONITOR or ALL.",
        {"band": {"type": "string", "enum": ["REDUCE_OR_REVIEW", "CONTINUE", "MONITOR", "ALL"]},
         "top_n": {"type": "integer", "description": "Number of clients, default 5"}}, ["band"]),
    _fn("board_risk_exposure", "Category A projects that are Past Due or on the Watchlist: approved, disbursed, "
                               "undisbursed and expected credit loss (Board question)."),
    _fn("simulate_exposure_reduction", "What-if: exposure before and after cancelling a share of a client's undisbursed commitments.",
        {"client": {"type": "string"}, "cancel_share": {"type": "number", "description": "0 to 1, e.g. 0.5 for 50%"}},
        ["client", "cancel_share"]),
    _fn("get_assumptions", "Business definitions and assumptions behind the figures.",
        {"topic": {"type": "string", "description": "Keyword such as exposure, committed, region; empty for all"}}),
    _fn("data_quality_summary", "Latest data-quality checks (expected vs actual) and known data issues."),
    _fn("ask_genie", "Ask the Genie portfolio analyst any other factual question about projects, regions, products, "
                     "timelines or volumes. Returns Genie's SQL and the result.",
        {"question": {"type": "string"}}, ["question"]),
]

# tool name -> (SQL template with named parameter markers, parameter types)
SQL_TOOLS = {
    "get_client_scorecard": (f"SELECT * FROM {FQ}.get_client_scorecard(:client)", {"client": "STRING"}),
    "get_client_projects": (f"SELECT * FROM {FQ}.get_client_projects(:client)", {"client": "STRING"}),
    "list_clients": (f"SELECT * FROM {FQ}.list_clients(:band, :top_n)", {"band": "STRING", "top_n": "INT"}),
    "board_risk_exposure": (f"SELECT * FROM {FQ}.board_risk_exposure()", {}),
    "simulate_exposure_reduction": (f"SELECT * FROM {FQ}.simulate_exposure_reduction(:client, :cancel_share)",
                                    {"client": "STRING", "cancel_share": "DOUBLE"}),
    "get_assumptions": (f"SELECT * FROM {FQ}.get_assumptions(:topic)", {"topic": "STRING"}),
    "data_quality_summary": (f"SELECT * FROM {FQ}.data_quality_summary()", {}),
}
DEFAULTS = {"top_n": 5, "topic": ""}
# Any answer that advises action (or answers a question asking for it) is advice to the Credit Risk Committee.
DECISION_PATTERN = re.compile(
    r"\b(recommend\w*|should|continue (?:to )?invest\w*|reduc\w*|under review|exit\w*|cut\w*|freez\w*|"
    r"increase exposure|next step|course of action|concern\w*|worr\w*)\b", re.I)


class SqlRunner:
    """Runs governed SQL on a SQL warehouse through the Statement Execution API (works in notebooks, serving and apps)."""

    def __init__(self, w: WorkspaceClient, warehouse_id: str):
        if not warehouse_id:
            raise ValueError("IFC_WAREHOUSE_ID is not set")
        self.w, self.warehouse_id = w, warehouse_id

    def run(self, statement: str, params: dict | None = None, types: dict | None = None, max_rows: int = 100) -> dict:
        parameters = [StatementParameterListItem(name=k, value=None if v is None else str(v), type=(types or {}).get(k, "STRING"))
                      for k, v in (params or {}).items()]
        resp = self.w.statement_execution.execute_statement(
            warehouse_id=self.warehouse_id, statement=statement, catalog=CATALOG, schema=SCHEMA,
            parameters=parameters or None, wait_timeout="30s")
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            time.sleep(1)
            resp = self.w.statement_execution.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            msg = resp.status.error.message if resp.status.error else str(resp.status.state)
            raise RuntimeError(msg)
        columns = [c.name for c in resp.manifest.schema.columns] if resp.manifest and resp.manifest.schema else []
        data = (resp.result.data_array or []) if resp.result else []
        return {"columns": columns, "rows": data[:max_rows], "row_count": len(data)}


class AdvisorCore:
    def __init__(self):
        self.w = WorkspaceClient()
        self.sql = SqlRunner(self.w, WAREHOUSE_ID)
        self.llm = self.w.serving_endpoints.get_open_ai_client()

    # ---- tools ---------------------------------------------------------------
    @mlflow.trace(span_type="TOOL")
    def call_tool(self, name: str, args: dict) -> dict:
        try:
            if name == "ask_genie":
                return self.ask_genie(args.get("question", ""))
            sql, types = SQL_TOOLS[name]
            params = {k: args.get(k, DEFAULTS.get(k)) for k in types}
            result = self.sql.run(sql, params, types)
            return {"tool": name, "sql": sql, "parameters": params, "source": "governed_uc_function", **result}
        except Exception as e:  # surfaced to the model and to the review status
            return {"tool": name, "error": f"{type(e).__name__}: {e}"}

    def ask_genie(self, question: str) -> dict:
        if not GENIE_SPACE_ID:
            return {"tool": "ask_genie", "error": "Genie space not configured (IFC_GENIE_SPACE_ID)"}
        msg = self.w.genie.start_conversation_and_wait(space_id=GENIE_SPACE_ID, content=question)
        out: dict[str, Any] = {"tool": "ask_genie", "question": question, "source": "genie_generated_sql"}
        for att in msg.attachments or []:
            if getattr(att, "text", None) is not None and att.text.content:
                out["genie_text"] = att.text.content
            if getattr(att, "query", None) is not None and att.query.query:
                out["sql"] = att.query.query
                out["genie_description"] = att.query.description
                # Re-run Genie's SQL on our warehouse so the figures shown are reproducible and logged.
                out.update(self.sql.run(att.query.query, max_rows=50))
        if "sql" not in out and "genie_text" not in out:
            out["error"] = "Genie returned no answer"
        return out

    # ---- agent loop ----------------------------------------------------------
    @mlflow.trace(span_type="AGENT")
    def run(self, messages: list[dict]) -> dict:
        started = time.time()
        convo = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
        trace = []
        answer = None
        for _ in range(MAX_STEPS):
            resp = self.llm.chat.completions.create(model=LLM_ENDPOINT, messages=convo, tools=TOOLS, temperature=0.0)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                answer = msg.content or ""
                break
            convo.append({"role": "assistant", "content": msg.content or "",
                          "tool_calls": [tc.model_dump() for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = self.call_tool(tc.function.name, args)
                trace.append({"tool": tc.function.name, "arguments": args, "sql": result.get("sql"),
                              "source": result.get("source"), "row_count": result.get("row_count"),
                              "error": result.get("error")})
                convo.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)[:15000]})
        if answer is None:
            answer = "I could not complete this request within the allowed number of steps. Please narrow the question."

        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        status, reasons = self.review_status(question, answer, trace)
        full = answer + self.evidence_footer(trace, status, reasons)
        latency = int((time.time() - started) * 1000)
        self.audit(question, full, status, trace, latency)
        return {"answer": full, "review_status": status, "review_reasons": reasons, "trace": trace, "latency_ms": latency}

    # ---- trust layer -----------------------------------------------------------
    @staticmethod
    def review_status(question: str, answer: str, trace: list) -> tuple[str, list]:
        reasons = []
        if not trace:
            reasons.append("no data tool was called")
        if any(t.get("error") for t in trace):
            reasons.append("a tool returned an error")
        if any(t.get("row_count") == 0 for t in trace):
            reasons.append("a tool returned no rows")
        if DECISION_PATTERN.search(question) or DECISION_PATTERN.search(answer):
            reasons.append("contains a recommendation (advice to the Credit Risk Committee, not a decision)")
        if reasons:
            return "HUMAN_REVIEW_REQUIRED", reasons
        if any(t.get("source") == "genie_generated_sql" for t in trace):
            return "REVIEW_RECOMMENDED", ["figures come from Genie-generated SQL (shown below), not a pre-validated function"]
        return "VALIDATED", ["all figures come from governed Unity Catalog functions"]

    @staticmethod
    def evidence_footer(trace: list, status: str, reasons: list) -> str:
        lines = ["", "", "---", f"**Review status: {status}** ({'; '.join(reasons)})", "", "**How this answer was produced:**"]
        for i, t in enumerate(trace, 1):
            args = ", ".join(f"{k}={v!r}" for k, v in (t.get("arguments") or {}).items())
            line = f"{i}. `{t['tool']}({args})`"
            if t.get("error"):
                line += f" - error: {t['error']}"
            elif t.get("row_count") is not None:
                line += f" - {t['row_count']} rows"
            lines.append(line)
            if t.get("sql"):
                lines.append(f"   SQL: `{' '.join(t['sql'].split())[:400]}`")
        lines.append("Definitions: ref_assumptions. Full record: agent_audit_log.")
        return "\n".join(lines)

    def audit(self, question, answer, status, trace, latency_ms):
        try:
            user = self.w.current_user.me().user_name
        except Exception:
            user = "unknown"
        try:
            self.sql.run(
                f"INSERT INTO {FQ}.agent_audit_log VALUES (:rid, current_timestamp(), :usr, :q, :a, :st, :tools, :model, :lat)",
                {"rid": str(uuid.uuid4()), "usr": user, "q": question, "a": answer, "st": status,
                 "tools": json.dumps(trace, default=str), "model": LLM_ENDPOINT, "lat": latency_ms},
                {"lat": "BIGINT"})
        except Exception as e:
            print(f"audit log write failed: {e}")


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    return ""


class CFODecisionAdvisor(ResponsesAgent):
    """MLflow ResponsesAgent wrapper: makes the advisor loggable, servable and usable in the Review App and AI Playground."""

    def __init__(self):
        self._core = None

    @property
    def core(self) -> AdvisorCore:
        if self._core is None:  # created lazily so logging the model needs no credentials
            self._core = AdvisorCore()
        return self._core

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        messages = []
        for item in request.input:
            d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            role, content = d.get("role"), _text(d.get("content"))
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})
        result = self.core.run(messages)
        return ResponsesAgentResponse(
            output=[{"type": "message", "id": str(uuid.uuid4()), "role": "assistant",
                     "content": [{"type": "output_text", "text": result["answer"]}]}],
            custom_outputs={"review_status": result["review_status"], "review_reasons": result["review_reasons"],
                            "tool_trace": json.loads(json.dumps(result["trace"], default=str))})


AGENT = CFODecisionAdvisor()
mlflow.models.set_model(AGENT)
