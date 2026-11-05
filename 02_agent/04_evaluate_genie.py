# Databricks notebook source
# MAGIC %md
# MAGIC # 04_evaluate_genie — same question, many phrasings, one answer?
# MAGIC
# MAGIC The client's problem: two departments gave the Board different figures for the same measure. This notebook measures
# MAGIC whether our Genie space gives the **same, correct** figure however a question is phrased.
# MAGIC
# MAGIC For every WS1 question in `02_agent/genie_paraphrases.yml` (the original wording + 4 reviewed paraphrases):
# MAGIC 1. Ask Genie through the Conversation API.
# MAGIC 2. Re-run the SQL Genie wrote, ourselves, on the certified table.
# MAGIC 3. Compare with the certified answer in `answers_register`: every key figure must appear in Genie's result (within
# MAGIC    0.5%); for lists, the row count must match too.
# MAGIC 4. Deterministic caveat: if Genie's SQL reads only `certified_investment_portfolio` with a simple WHERE, count how many
# MAGIC    projects in that scope have open data-quality issues (the same counts the certified answers carry). If the SQL is
# MAGIC    too complex to analyse, say so.
# MAGIC
# MAGIC | Score | Meaning |
# MAGIC |---|---|
# MAGIC | **Accuracy** | Share of phrasings whose result matches the certified answer |
# MAGIC | **Consistency** | Share of questions where **all** phrasings returned the same key figures (right or wrong) |
# MAGIC | **Fully reliable** | Share of questions where every phrasing is accurate |
# MAGIC
# MAGIC Results go to `genie_eval_results` (one row per phrasing) and `genie_eval_summary` (one row per question per run),
# MAGIC and to MLflow. Settings (which questions, delay between calls, tolerance) are in the `evaluation` section of the config.

# COMMAND ----------

# MAGIC %pip install sqlglot pyyaml --quiet

# COMMAND ----------

# MAGIC %run ../00_setup/00_config

# COMMAND ----------

import json
import math
import time
import uuid
from datetime import datetime, timezone

import yaml
from databricks.sdk import WorkspaceClient

EVAL = CFG.get("evaluation", {})
TOL = float(EVAL.get("relative_tolerance", 0.005))
DELAY = float(EVAL.get("delay_seconds", 10))
SELECTED = EVAL.get("questions", "all")
INCLUDE_ORIGINAL = bool(EVAL.get("include_original", True))
CERT = T("certified_investment_portfolio")

assert GENIE_SPACE_ID, "Set serving.genie_space_id in config (run 02_agent/01_genie_space first)."
w = WorkspaceClient()

with open(REPO_ROOT / EVAL.get("paraphrases_file", "02_agent/genie_paraphrases.yml")) as f:
    PARA = yaml.safe_load(f)["questions"]
if SELECTED != "all":
    PARA = [q for q in PARA if q["id"] in set(SELECTED)]
print(f"{len(PARA)} questions; delay {DELAY}s between Genie calls; tolerance {TOL:.1%}")

# The paraphrase set as a table, so it is visible next to the results.
spark.createDataFrame(
    [(q["id"], 0, q["original"]) for q in PARA] + [(q["id"], i, p) for q in PARA for i, p in enumerate(q["paraphrases"], 1)],
    "question_id STRING, paraphrase_no INT, text STRING").write.mode("overwrite").saveAsTable(T("genie_paraphrases"))

# COMMAND ----------

# MAGIC %md ## Ground truth and comparison

# COMMAND ----------


def rows_of(sql: str) -> list:
    return [r.asDict() for r in spark.sql(sql).collect()]


def numbers(rows: list) -> list:
    out = []
    for r in rows:
        for v in r.values():
            if isinstance(v, bool) or v is None:
                continue
            try:
                x = float(v)
            except (TypeError, ValueError):
                continue
            if not math.isnan(x):
                out.append(x)
    return out


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(abs(a), abs(b)) * TOL + 0.01


def key_values(q: dict, rows: list) -> list:
    """The certified figures that Genie must reproduce."""
    vals = []
    for r in rows:
        if q.get("ignore_total") and any(str(v) == "TOTAL" for v in r.values()):
            continue
        for c in q["key_columns"]:
            v = r.get(c, r.get(int(c)) if str(c).isdigit() else None)
            if v is not None and not isinstance(v, bool):
                vals.append(float(v))
    return vals


def compare(q: dict, truth_rows: list, genie_rows: list) -> dict:
    expected = key_values(q, truth_rows)
    got = numbers(genie_rows)
    missing = [e for e in expected if not any(close(e, g) for g in got)]
    rows_ok = (not q.get("check_rows")) or len(genie_rows) == len(truth_rows)
    return {"accurate": not missing and rows_ok and len(expected) > 0, "expected_values": len(expected),
            "missing_values": len(missing), "rows_ok": rows_ok, "missing_sample": missing[:5],
            "signature": tuple(sorted(round(g, 2) for g in got if any(close(g, e) for e in expected)))}


truth = {}
for q in PARA:
    sql = spark.sql(f"SELECT sql_text FROM {T('answers_register')} WHERE workstream = 'WS1' AND question_id = '{q['certified']}'").first()
    assert sql, f"No certified answer {q['certified']} in answers_register; run 04_answers/ws1 first."
    truth[q["id"]] = rows_of(sql[0])

# COMMAND ----------

# MAGIC %md ## Deterministic caveat for Genie's SQL

# COMMAND ----------

import sqlglot  # noqa: E402
from sqlglot import exp  # noqa: E402


def caveat(genie_sql: str) -> dict:
    """Flag counts for the projects Genie's query covers, when its scope can be read off the SQL."""
    try:
        tree = sqlglot.parse_one(genie_sql, read="databricks")
        tables = {t.sql(dialect="databricks").split(" AS ")[0].replace("`", "").lower() for t in tree.find_all(exp.Table)}
        simple = (tables == {CERT.lower()} and not tree.find(exp.Join) and not tree.find(exp.With)
                  and not tree.find(exp.Union) and len(list(tree.find_all(exp.Select))) == 1)
        if not simple:
            return {"caveat_status": "not analysable (joins, CTEs or subqueries)"}
        where = tree.args.get("where")
        cond = where.this.sql(dialect="databricks") if where else "TRUE"
        r = spark.sql(f"""SELECT count(*) AS n, count_if(needs_review) AS review, count_if(dq_max_severity = 'high') AS high,
                                 count_if(text_attributes_need_review) AS text FROM {CERT} WHERE {cond}""").first()
        return {"caveat_status": "computed", "rows_in_scope": r["n"], "rows_needing_review": r["review"],
                "rows_high_severity": r["high"], "rows_text_review": r["text"]}
    except Exception as e:  # never let the caveat break the evaluation
        return {"caveat_status": f"not analysable ({type(e).__name__})"}


# COMMAND ----------

# MAGIC %md ## Ask Genie

# COMMAND ----------


def ask_genie(text: str) -> dict:
    t0 = time.time()
    try:
        msg = w.genie.start_conversation_and_wait(GENIE_SPACE_ID, text)
        sql, answer_text = None, None
        for a in msg.attachments or []:
            if getattr(a, "query", None) and a.query.query:
                sql = a.query.query
            if getattr(a, "text", None) and a.text.content:
                answer_text = a.text.content
        return {"status": str(msg.status.value if msg.status else ""), "genie_sql": sql, "genie_text": answer_text,
                "conversation_id": msg.conversation_id, "latency_s": round(time.time() - t0, 1), "error": None}
    except Exception as e:
        return {"status": "ERROR", "genie_sql": None, "genie_text": None, "conversation_id": None,
                "latency_s": round(time.time() - t0, 1), "error": f"{type(e).__name__}: {e}"[:500]}


RUN_ID = str(uuid.uuid4())
RUN_AT = datetime.now(timezone.utc).isoformat()
results = []
for q in PARA:
    phrasings = ([(0, q["original"])] if INCLUDE_ORIGINAL else []) + list(enumerate(q["paraphrases"], 1))
    for no, text in phrasings:
        g = ask_genie(text)
        row = {"run_id": RUN_ID, "run_at": RUN_AT, "question_id": q["id"], "paraphrase_no": no, "text": text, **g}
        if g["genie_sql"]:
            try:
                genie_rows = rows_of(g["genie_sql"])
                cmp = compare(q, truth[q["id"]], genie_rows)
                row.update(genie_rows=len(genie_rows), **{k: v for k, v in cmp.items() if k != "signature"},
                           signature=json.dumps(cmp["signature"]), **caveat(g["genie_sql"]))
            except Exception as e:
                row.update(accurate=False, error=f"Genie SQL failed when re-run: {type(e).__name__}: {e}"[:500])
        else:
            row.update(accurate=False)
        results.append(row)
        print(f"{q['id']} #{no} {'OK  ' if row.get('accurate') else 'MISS'} {text[:80]}")
        time.sleep(DELAY)

# COMMAND ----------

# MAGIC %md ## Store and score

# COMMAND ----------

import pandas as pd  # noqa: E402

COLS = ["run_id", "run_at", "question_id", "paraphrase_no", "text", "status", "genie_sql", "genie_text", "conversation_id",
        "latency_s", "error", "genie_rows", "accurate", "expected_values", "missing_values", "rows_ok", "signature",
        "caveat_status", "rows_in_scope", "rows_needing_review", "rows_high_severity", "rows_text_review"]
pdf = pd.DataFrame([{c: r.get(c) for c in COLS} for r in results])
for c in ["genie_rows", "expected_values", "missing_values", "rows_in_scope", "rows_needing_review",
          "rows_high_severity", "rows_text_review"]:
    pdf[c] = pdf[c].astype("Int64")
pdf["accurate"] = pdf["accurate"].fillna(False).astype(bool)
spark.createDataFrame(pdf.astype(object).where(pdf.notna(), None)).write.mode("append").option("mergeSchema", "true") \
    .saveAsTable(T("genie_eval_results"))

summary = []
for qid, grp in pdf.groupby("question_id", sort=True):
    sigs = set(grp["signature"].fillna("none"))
    summary.append({"run_id": RUN_ID, "run_at": RUN_AT, "question_id": qid, "phrasings": len(grp),
                    "accurate": int(grp["accurate"].sum()), "accuracy": round(float(grp["accurate"].mean()), 3),
                    # same key figures from every phrasing (and at least one figure found), or all accurate
                    "consistent": (len(sigs) == 1 and not sigs & {"none", "[]"}) or bool(grp["accurate"].all()),
                    "fully_reliable": bool(grp["accurate"].all())})
sdf = pd.DataFrame(summary)
spark.createDataFrame(sdf).write.mode("append").saveAsTable(T("genie_eval_summary"))

overall = {"accuracy": round(float(pdf["accurate"].mean()), 3),
           "consistency": round(float(sdf["consistent"].mean()), 3),
           "fully_reliable": round(float(sdf["fully_reliable"].mean()), 3),
           "questions": len(sdf), "phrasings": len(pdf)}
print(json.dumps(overall, indent=1))
display(spark.createDataFrame(sdf))  # noqa: F821

try:
    import mlflow
    me = spark.sql("SELECT current_user()").first()[0]
    mlflow.set_experiment(f"/Users/{me}/{EVAL.get('mlflow_experiment', 'ifc_genie_evaluation')}")
    with mlflow.start_run(run_name=f"genie-eval-{RUN_AT[:16]}"):
        mlflow.log_params({"genie_space_id": GENIE_SPACE_ID, "questions": overall["questions"],
                           "phrasings": overall["phrasings"], "tolerance": TOL, "run_id": RUN_ID})
        mlflow.log_metrics({k: v for k, v in overall.items() if isinstance(v, float)})
        mlflow.log_table(sdf, "per_question.json")
    print("Logged to MLflow")
except Exception as e:
    print(f"MLflow logging skipped ({type(e).__name__}: {e})")
