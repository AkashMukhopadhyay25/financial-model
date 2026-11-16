"""
Ask the Genie space (Genie Conversation API) and return a governed answer:
  Genie's text, the SQL it wrote, the result rows, suggested follow-ups,
  + a deterministic trust check on that SQL (trust.py),
  + the closest certified WS1 answer, when the question matches one (consistency check).

The app talks to a Genie *space* (AI/BI Genie). Genie Code, the in-editor assistant, has no API for apps.
"""
from datetime import timedelta

from . import queries, trust
from .settings import get_settings
from .sql import get_db, statement_to_rows

MAX_ROWS = 500


def _client():
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient()


def ask(question: str, conversation_id: str = None) -> dict:
    s = get_settings()
    match = queries.match_certified(question)
    base = {"question": question, "certified_match": match}
    if s.data_mode == "local" or not s.genie_space_id:
        why = ("Local preview: Genie is available only in the deployed app."
               if s.data_mode == "local" else
               "No Genie space is configured. Add the 'genie-space' resource to the app (see 03_demo/app/README.md).")
        return {**base, "available": False, "status": "UNAVAILABLE", "text": why, "sql": None, "columns": [],
                "rows": [], "suggested_questions": [],
                "trust": {"level": "HUMAN_REVIEW_REQUIRED", "color": "red", "counts": None,
                          "reasons": ["Genie did not answer; use the certified answer library instead."]}}

    w = _client()
    timeout = timedelta(seconds=180)
    if conversation_id:
        msg = w.genie.create_message_and_wait(s.genie_space_id, conversation_id, question, timeout=timeout)
    else:
        msg = w.genie.start_conversation_and_wait(s.genie_space_id, question, timeout=timeout)

    text_parts, sql, description, columns, rows, suggested = [], None, None, [], [], []
    for att in msg.attachments or []:
        if att.text and att.text.content:
            text_parts.append(att.text.content)
        if att.query:
            sql = att.query.query
            description = att.query.description
            try:
                res = w.genie.get_message_attachment_query_result(
                    s.genie_space_id, msg.conversation_id, msg.id, att.attachment_id)
                columns, rows = statement_to_rows(res.statement_response)
            except Exception as e:  # result expired or not available: re-run the SQL ourselves
                try:
                    rows = get_db().query(sql)
                    columns = list(rows[0].keys()) if rows else []
                except Exception:
                    text_parts.append(f"(The query result could not be retrieved: {type(e).__name__}.)")
        if getattr(att, "suggested_questions", None) and att.suggested_questions.questions:
            suggested = list(att.suggested_questions.questions)

    status = msg.status.value if msg.status else "UNKNOWN"
    error = msg.error.error if msg.error else None
    return {**base, "available": True, "status": status, "error": error,
            "conversation_id": msg.conversation_id, "message_id": msg.id,
            "text": "\n\n".join(text_parts) or description or "", "description": description,
            "sql": sql, "columns": columns, "rows": rows[:MAX_ROWS], "row_count": len(rows),
            "suggested_questions": suggested,
            "trust": trust.assess(sql, bool(rows), get_db(), s.table(trust.PORTFOLIO))}


def send_feedback(conversation_id: str, message_id: str, positive: bool) -> dict:
    from databricks.sdk.service.dashboards import GenieFeedbackRating

    s = get_settings()
    _client().genie.send_message_feedback(s.genie_space_id, conversation_id, message_id,
                                          GenieFeedbackRating.POSITIVE if positive else GenieFeedbackRating.NEGATIVE)
    return {"ok": True}
