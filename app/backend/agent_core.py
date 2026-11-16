"""
Shared core for the team's own agents (Genie answers "what happened?"; our agents answer "so what?").

One loop, one set of guardrails, one audit trail; each agent brings only its instructions, tools and model:
  * The model chooses tools and writes the explanation. It never computes a figure: every number comes from a tool
    (deterministic SQL on the certified tables), so a scenario returns the same numbers however it is asked.
  * Number tracing (deterministic, after the model answers): every figure in the answer must appear in a tool result
    in this conversation. Figures that cannot be traced are listed and the answer is marked for review.
  * Trust levels as elsewhere in the app: VALIDATED (green) / REVIEW_RECOMMENDED (amber) / HUMAN_REVIEW_REQUIRED (red),
    with reasons always listed.
  * Every run is logged to ops_agent_runs (question, answer, tools, SQL, trust level, model, latency).

The model is a Databricks-hosted open-weight model (Foundation Model API, pay-per-token), named in the config,
so it can be swapped without code changes.
"""
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from .queries import T, q

log = logging.getLogger("ifc_app.agent")


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable[..., dict]
    required: list = field(default_factory=list)

    def spec(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name, "description": self.description,
            "parameters": {"type": "object", "properties": self.parameters, "required": self.required}}}


@dataclass
class AgentSpec:
    name: str                 # e.g. "stress_test"
    title: str                # shown in the UI
    model: str                # serving endpoint name
    instructions: str
    tools: list
    max_steps: int = 6


def _client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient().serving_endpoints.get_open_ai_client()


def _text(content) -> str:
    """Message content as plain text (some endpoints return a list of blocks, incl. reasoning blocks)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    out = []
    for b in content:
        b = b if isinstance(b, dict) else getattr(b, "__dict__", {})
        if b.get("type") in ("text", "output_text"):
            out.append(b.get("text") or "")
    return "".join(out)


# ---------------------------------------------------------------- number tracing
NUM = re.compile(r"(?<![\w.])-?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|[MB]\b)?")


def _numbers_in(obj, out: set):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.add(float(obj))
    elif isinstance(obj, str):
        for m in NUM.finditer(obj):
            v = _parse(m.group(0))
            if v is not None:
                out.add(v)
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers_in(v, out)


def _parse(token: str):
    t = token.strip().replace("$", "").replace(",", "")
    scale = 1.0
    if t.endswith("%"):
        t, scale = t[:-1].strip(), 0.01
    elif t.endswith("B"):
        t, scale = t[:-1].strip(), 1000.0
    elif t.endswith("M"):
        t = t[:-1].strip()
    try:
        return float(t) * scale
    except ValueError:
        return None


def _derived(values: set) -> set:
    """Figures the model may state: the tool values and their percentage forms (0.6 <-> 60%). Sums, differences and
    ratios the model works out itself are NOT accepted: the tools return every figure the answer needs."""
    out = set(values)
    out |= {v * 100 for v in values if abs(v) <= 1}      # 0.6 -> 60 (%)
    out |= {v / 100 for v in values}                     # 60 -> 0.6
    return out


def untraced_figures(answer: str, tool_results: list) -> list:
    known = set()
    for r in tool_results:
        _numbers_in(r, known)
    known = _derived(known)
    bad = []
    for m in NUM.finditer(answer):
        tok = m.group(0).strip()
        v = _parse(tok)
        if v is None:
            continue
        raw = tok.replace("$", "").replace(",", "").rstrip("%MB ").strip()
        if not tok.startswith("$") and not tok.endswith(("%", "M", "B")) and "." not in raw and abs(v) <= 31:
            continue  # small counts, list numbers, ratings, days: not monetary claims
        if 1990 <= v <= 2100 and "." not in raw and not tok.startswith("$"):
            continue  # years
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        # tolerance: the model may round or truncate a tool figure to the precision it wrote
        # (e.g. 10,109.45 -> $10,109M or $10.1B); anything further off is not that figure
        unit = 1000.0 if tok.endswith("B") else (0.01 if tok.endswith("%") else 1.0)
        tol = unit * (10 ** -decimals) - 1e-9
        if not any(abs(v - k) <= tol for k in known):
            bad.append(tok)
    return list(dict.fromkeys(bad))


# ---------------------------------------------------------------- the loop
def run(spec: AgentSpec, question: str, history: list = None, user: str = "") -> dict:
    t0 = time.time()
    tools = {t.name: t for t in spec.tools}
    convo = [{"role": "system", "content": spec.instructions}]
    for m in (history or [])[-6:]:
        if m.get("role") in ("user", "assistant") and m.get("content"):
            convo.append({"role": m["role"], "content": str(m["content"])[:4000]})
    convo.append({"role": "user", "content": question})

    trace, results, answer, error = [], [], "", None
    try:
        llm = _client()
        for _ in range(spec.max_steps):
            resp = llm.chat.completions.create(model=spec.model, messages=convo, tools=[t.spec() for t in spec.tools],
                                               temperature=0.0, max_tokens=1800)
            msg = resp.choices[0].message
            if not msg.tool_calls:
                answer = _text(msg.content).strip()
                break
            convo.append({"role": "assistant", "content": _text(msg.content) or "",
                          "tool_calls": [{"id": tc.id, "type": "function",
                                          "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                         for tc in msg.tool_calls]})
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                tool = tools.get(tc.function.name)
                if tool is None:
                    result = {"error": f"unknown tool {tc.function.name}"}
                else:
                    try:
                        result = tool.fn(**args)
                    except TypeError as e:
                        result = {"error": f"bad arguments: {e}"}
                    except Exception as e:  # SQL or connection failure: report, never guess
                        log.exception("tool %s failed", tool.name)
                        result = {"error": f"{type(e).__name__}: {e}"}
                results.append({"tool": tc.function.name, "arguments": args, "result": result})
                trace.append({"tool": tc.function.name, "arguments": args, "error": result.get("error"),
                              "sql": result.get("sql"), "rows": _row_count(result)})
                convo.append({"role": "tool", "tool_call_id": tc.id,
                              "content": json.dumps({k: v for k, v in result.items() if not k.startswith("sql")},
                                                    default=str)[:12000]})
        else:
            answer = answer or ""
        if not answer:
            error = "The agent did not finish within its step limit."
    except Exception as e:
        log.exception("agent %s failed", spec.name)
        error = f"{type(e).__name__}: {e}"

    trust = assess(answer, results, error)
    out = {"agent": spec.name, "title": spec.title, "model": spec.model, "question": question,
           "answer": answer or "", "error": error, "trace": trace,
           "results": [r for r in results if not r["result"].get("error")],
           "trust": trust, "latency_ms": int((time.time() - t0) * 1000)}
    out["run_id"] = _audit(spec, question, out, user)
    return out


def _row_count(result: dict):
    for k in ("rows", "breakdown", "top_projects"):
        if isinstance(result.get(k), list):
            return len(result[k])
    return 1 if result.get("summary") else 0


def assess(answer: str, results: list, error) -> dict:
    ok = [r for r in results if not r["result"].get("error")]
    reasons = []
    if error or not answer:
        return {"level": "HUMAN_REVIEW_REQUIRED", "color": "red",
                "reasons": [error or "No answer was produced."], "untraced_figures": []}
    if not ok:
        return {"level": "HUMAN_REVIEW_REQUIRED", "color": "red", "untraced_figures": [],
                "reasons": ["No data tool returned a result, so the answer cannot be traced to governed data."]}
    failed = [r["tool"] for r in results if r["result"].get("error")]
    if failed:
        reasons.append(f"{len(failed)} tool call(s) failed and were retried or skipped ({', '.join(sorted(set(failed)))}).")
    bad = untraced_figures(answer, [r["result"] for r in ok])
    if bad:
        reasons.append(f"{len(bad)} figure(s) in the answer could not be traced to a tool result: {', '.join(bad[:6])}.")
    else:
        reasons.append("Every figure in the answer was traced to a tool result (deterministic SQL on certified tables).")
    high = sum(int((r["result"].get("summary") or {}).get("shocked_projects_high_severity") or 0) for r in ok)
    dq = sum(int((r["result"].get("summary") or {}).get("shocked_projects_with_dq_issues") or 0) for r in ok)
    if dq:
        reasons.append(f"{dq} shocked project(s) have open data-quality issues ({high} high severity); included, not excluded.")
    level = "REVIEW_RECOMMENDED" if (bad or high) else "VALIDATED"
    return {"level": level, "color": "amber" if level == "REVIEW_RECOMMENDED" else "green",
            "reasons": reasons, "untraced_figures": bad}


# ---------------------------------------------------------------- audit trail
def _ensure_runs_table():
    q(f"""CREATE TABLE IF NOT EXISTS {T('ops_agent_runs')} (
  run_id STRING, asked_at TIMESTAMP, asked_by STRING, agent STRING, model STRING, question STRING, answer STRING,
  trust_level STRING, tools_json STRING, latency_ms BIGINT, response_json STRING)
COMMENT 'Every question answered by the team''s own agents: answer, tools and SQL used, trust level, model and latency.'""")


def _audit(spec: AgentSpec, question: str, out: dict, user: str):
    rid = uuid.uuid4().hex
    try:
        _ensure_runs_table()
        q(f"""INSERT INTO {T('ops_agent_runs')}
SELECT :rid, now(), :by, :agent, :model, :question, :answer, :level, :tools, CAST(:lat AS BIGINT), :resp""",
          {"rid": rid, "by": user or "", "agent": spec.name, "model": spec.model, "question": question,
           "answer": out.get("answer") or out.get("error") or "", "level": out["trust"]["level"],
           "tools": json.dumps(out["trace"], default=str), "lat": out["latency_ms"],
           "resp": json.dumps(out, default=str)})
    except Exception:
        log.exception("agent audit failed")
        return None  # the audit trail is best effort: never block the answer
    return rid


def recent_runs(agent: str, limit: int = 20) -> list:
    try:
        return q(f"""SELECT run_id, CAST(asked_at AS STRING) AS asked_at, asked_by, question, trust_level, latency_ms
FROM {T('ops_agent_runs')} WHERE agent = :agent ORDER BY asked_at DESC LIMIT {int(limit)}""", {"agent": agent})
    except Exception:
        return []


def get_run(run_id: str):
    try:
        rows = q(f"SELECT response_json FROM {T('ops_agent_runs')} WHERE run_id = :rid", {"rid": run_id})
    except Exception:
        return None
    return json.loads(rows[0]["response_json"]) if rows else None
