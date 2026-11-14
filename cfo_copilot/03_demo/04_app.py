"""CFO Portfolio Advisor: Databricks App (Streamlit) for IFC's CFO Office.

Tabs
  1. Ask the Advisor   - chat with the CFO Decision Advisor (agent + Genie); every answer shows evidence and review status
  2. Board risk view   - WS2: Category A Past Due / Watchlist exposure and loss provision
  3. Client decisions  - WS3: scorecard by band, drill-down to project evidence, the four recommendations
  4. Trust & quality   - data-quality checks, assumptions, recent agent answers awaiting review
  5. Monthly trends    - KPIs month by month, any two months compared, the project changes behind each movement
  6. Upload a month    - put a month of files in the landing zone and run the monthly pipeline job

Deploy: Compute -> Apps -> Create app -> source code path = the team folder (app.yaml sits there).
Configuration via app.yaml environment variables; credentials come from the app's service principal.
"""
import io
import os
import re
import sys

import pandas as pd
import streamlit as st

sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "02_agent"))
import cfo_agent  # noqa: E402  (same agent code that is logged and served from 03_build_agent)

st.set_page_config(page_title="CFO Portfolio Advisor", layout="wide")


@st.cache_resource
def core():
    return cfo_agent.AdvisorCore()


def query(sql: str) -> pd.DataFrame:
    r = core().sql.run(sql, max_rows=5000)
    return pd.DataFrame(r["rows"], columns=r["columns"])


def md(text: str) -> str:
    """Escape $ so Streamlit does not render dollar amounts as LaTeX maths."""
    return text.replace("$", "\\$")


def num(df, cols):
    for c in cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


FQ = cfo_agent.FQ
st.title("CFO Portfolio Advisor")
st.caption("IFC CFO Office · governed data on Databricks · every figure traceable to its SQL · amounts in USD millions")

tab_ask, tab_board, tab_clients, tab_trust, tab_trend, tab_upload = st.tabs(
    ["Ask the Advisor", "Board risk view", "Client decisions", "Trust & quality", "Monthly trends", "Upload a month"])

# ---- 1. chat -------------------------------------------------------------------------------------------
with tab_ask:
    st.write("Ask a portfolio or client question in plain language.")
    examples = ["Which clients should the Board be most concerned about?",
                "Which Category A projects are Past Due or on the Watchlist, and what should we provision?",
                "Which two clients should we continue to invest in, and why?",
                "What was total approved investment by region last year?"]
    cols = st.columns(len(examples))
    for c, ex in zip(cols, examples):
        if c.button(ex, use_container_width=True):
            st.session_state["pending"] = ex
    if "chat" not in st.session_state:
        st.session_state["chat"] = []
    for m in st.session_state["chat"]:
        with st.chat_message(m["role"]):
            st.markdown(md(m["content"]))
    prompt = st.chat_input("e.g. Why is this client flagged? Show me the evidence.") or st.session_state.pop("pending", None)
    if prompt:
        st.session_state["chat"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(md(prompt))
        with st.chat_message("assistant"):
            with st.spinner("Planning, querying governed data, checking evidence..."):
                result = core().run([{"role": m["role"], "content": m["content"]} for m in st.session_state["chat"]])
            badge = {"VALIDATED": "🟢", "REVIEW_RECOMMENDED": "🟡", "HUMAN_REVIEW_REQUIRED": "🔴"}[result["review_status"]]
            st.markdown(f"{badge} **{result['review_status'].replace('_', ' ').title()}**")
            st.markdown(md(result["answer"]))
        st.session_state["chat"].append({"role": "assistant", "content": result["answer"]})

# ---- 2. Board risk view (WS2) ----------------------------------------------------------------------------
with tab_board:
    br = num(query(f"SELECT * FROM {FQ}.board_risk_exposure()"),
             ["projects", "clients", "approved_musd", "disbursed_musd", "undisbursed_commitment_musd", "expected_credit_loss_musd"])
    tot = br[br.performance_status == "TOTAL"].iloc[0]
    k = st.columns(4)
    k[0].metric("Category A projects at risk", f"{int(tot.projects)}", f"{int(tot.clients)} clients", delta_color="off")
    k[1].metric("Approved", f"${tot.approved_musd:,.0f}M")
    k[2].metric("Disbursed capital tied up", f"${tot.disbursed_musd:,.0f}M")
    k[3].metric("Recommended provision (ECL)", f"${tot.expected_credit_loss_musd:,.0f}M")
    st.dataframe(br, hide_index=True, use_container_width=True)
    st.subheader("Projects")
    st.dataframe(query(f"""
        SELECT client_name, project_number, project_name, country, performance_status, internal_risk_rating,
               round(total_approved_musd, 1) AS approved_musd, round(disbursed_musd, 1) AS disbursed_musd,
               round(expected_credit_loss_musd, 1) AS ecl_musd
        FROM {FQ}.gold_portfolio
        WHERE environmental_category = 'A' AND performance_status IN ('Past Due', 'Watchlist')
        ORDER BY performance_status, total_approved_musd DESC"""), hide_index=True, use_container_width=True)
    st.caption("ECL = 60% of disbursed on Past Due projects (case brief). Watchlist carries no provision in this simplified model.")

# ---- 3. Client decisions (WS3) ---------------------------------------------------------------------------
with tab_clients:
    try:
        recs = num(query(f"""SELECT recommendation, client_name, client_id, exposure_affected_musd,
                                 current_disbursed_exposure_musd, undisbursed_commitment_musd, expected_credit_loss_musd,
                                 evidence_summary, suggested_action FROM {FQ}.ws3_recommendations"""),
                   ["exposure_affected_musd", "current_disbursed_exposure_musd", "undisbursed_commitment_musd", "expected_credit_loss_musd"])
        st.subheader("Recommendations to the Board (draft for Credit Risk Committee review)")
        c1, c2 = st.columns(2)
        for col, rec, title in [(c1, "CONTINUE", "🟢 Continue to invest"), (c2, "REDUCE_OR_REVIEW", "🔴 Reduce / review")]:
            with col:
                st.markdown(f"#### {title}")
                for _, r in recs[recs.recommendation == rec].iterrows():
                    st.markdown(md(f"**{r.client_name}** ({r.client_id}) · exposure affected **${r.exposure_affected_musd:,.0f}M** "
                                   f"(disbursed ${r.current_disbursed_exposure_musd:,.0f}M + undisbursed ${r.undisbursed_commitment_musd:,.0f}M)  \n"
                                   f"{r.evidence_summary}  \n_{r.suggested_action}_"))
    except Exception:
        st.info("Run 04_answers/ws3 to publish the recommendations.")

    st.subheader("All clients")
    band = st.radio("Band", ["REDUCE_OR_REVIEW", "MONITOR", "CONTINUE", "ALL"], horizontal=True)
    lst = query(f"SELECT * FROM {FQ}.list_clients('{band}', 400)")
    st.dataframe(lst, hide_index=True, use_container_width=True)
    pick = st.selectbox("Drill down to a client", lst["client_name"].tolist() if len(lst) else [])
    if pick:
        safe = pick.replace("'", "''")
        st.dataframe(query(f"SELECT * FROM {FQ}.get_client_scorecard('{safe}')").T, use_container_width=True)
        st.dataframe(query(f"SELECT * FROM {FQ}.get_client_projects('{safe}')"), hide_index=True, use_container_width=True)

# ---- 4. Trust & quality ----------------------------------------------------------------------------------
with tab_trust:
    st.subheader("Data-quality checks (latest run)")
    st.dataframe(query(f"SELECT * FROM {FQ}.data_quality_summary() ORDER BY check_id"), hide_index=True, use_container_width=True)
    st.subheader("Business definitions and assumptions")
    st.dataframe(query(f"SELECT * FROM {FQ}.get_assumptions('')"), hide_index=True, use_container_width=True)
    st.subheader("Recent agent answers requiring human review")
    st.dataframe(query(f"""SELECT asked_at, user_name, question, review_status, latency_ms FROM {FQ}.agent_audit_log
                           WHERE review_status <> 'VALIDATED' ORDER BY asked_at DESC LIMIT 50"""),
                 hide_index=True, use_container_width=True)

# ---- 5. Monthly trends -----------------------------------------------------------------------------------
# Monthly history lives in its own schema (01_data/run_monthly_pipeline writes kpi_monthly, kpi_month_over_month,
# compare_months(), project_month_changes, ops_monthly_loads there).
MFQ = f"{os.environ.get('IFC_CATALOG', 'workspace')}.{os.environ.get('IFC_MONTHLY_SCHEMA', 'portfolio_monthly_dev')}"
DIMENSIONS = ["Portfolio", "Region", "Industry", "Product line", "Department"]
ASSESS_ICON = {"Improving": "🟢", "Deteriorating": "🔴", "Stable": "⚪", "Up": "🔼", "Down": "🔽"}

with tab_trend:
    try:
        months = query(f"SELECT DISTINCT month_label FROM {MFQ}.kpi_monthly ORDER BY 1")["month_label"].tolist()
    except Exception:
        months = []
    if len(months) < 2:
        st.info("Monthly history needs at least two loaded months. Upload them in **Upload a month**, "
                "or run 01_data/run_monthly_pipeline.")
    else:
        st.caption(f"{len(months)} reporting months loaded: {months[0]} to {months[-1]}. "
                   "Each month is a certified snapshot; a corrected re-upload replaces only its own month.")
        c1, c2, c3 = st.columns(3)
        month_a = c1.selectbox("From month", months, index=len(months) - 2)
        month_b = c2.selectbox("To month", months, index=len(months) - 1)
        dim = c3.selectbox("Breakdown", DIMENSIONS)
        cmp = num(query(f"SELECT * FROM {MFQ}.compare_months('{month_a}', '{month_b}', '{dim}')"),
                  ["value_a", "value_b", "change", "change_pct"])
        cmp["assessment"] = cmp["assessment"].map(lambda a: f"{ASSESS_ICON.get(a, '')} {a}" if a else "")
        if dim == "Portfolio":
            good = cmp[cmp.assessment.str.contains("Improving")]
            bad = cmp[cmp.assessment.str.contains("Deteriorating")]
            k = st.columns(3)
            k[0].metric("KPIs improving", len(good))
            k[1].metric("KPIs deteriorating", len(bad))
            k[2].metric("KPIs stable / neutral", len(cmp) - len(good) - len(bad))
            l, r = st.columns(2)
            cols = ["kpi_name", "unit", "value_a", "value_b", "change_pct"]
            l.markdown("#### 🟢 Going well")
            l.dataframe(good.sort_values("change_pct", key=abs, ascending=False)[cols], hide_index=True, use_container_width=True)
            r.markdown("#### 🔴 Needs attention")
            r.dataframe(bad.sort_values("change_pct", key=abs, ascending=False)[cols], hide_index=True, use_container_width=True)
        else:
            kpi_pick = st.selectbox("KPI", sorted(cmp["kpi_name"].dropna().unique()))
            st.dataframe(cmp[cmp.kpi_name == kpi_pick].sort_values("change_pct", key=abs, ascending=False)
                         [["dimension_value", "value_a", "value_b", "change", "change_pct", "assessment"]],
                         hide_index=True, use_container_width=True)
        with st.expander("All KPIs compared"):
            st.dataframe(cmp, hide_index=True, use_container_width=True)

        st.subheader("Trend over all months")
        series = num(query(f"""SELECT month_label, kpi_name, value FROM {MFQ}.kpi_monthly
                               WHERE dimension = 'Portfolio' ORDER BY month_label"""), ["value"])
        names = sorted(series.kpi_name.unique())
        default = [n for n in names if re.search(r"past due|watchlist|disbursed|review overdue", n, re.I)][:4] or names[:3]
        chosen = st.multiselect("KPIs to chart", names, default=default)
        if chosen:
            st.line_chart(series[series.kpi_name.isin(chosen)].pivot(index="month_label", columns="kpi_name", values="value"))

        st.subheader(f"Why it moved: project changes {month_a} → {month_b}")
        chg = num(query(f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, change_type, impact,
                                   count(*) AS projects, round(sum(amount_musd), 1) AS amount_musd
                            FROM {MFQ}.project_month_changes
                            WHERE date_format(reporting_month, 'yyyy-MM') > '{month_a}'
                              AND date_format(reporting_month, 'yyyy-MM') <= '{month_b}'
                            GROUP BY ALL ORDER BY month, projects DESC"""), ["projects", "amount_musd"])
        st.dataframe(chg, hide_index=True, use_container_width=True)
        types = chg["change_type"].unique().tolist() if len(chg) else []
        ct = st.selectbox("Show the projects for", types) if types else None
        if ct:
            st.dataframe(query(f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, client_name, project_name, region,
                                          industry, from_value, to_value, round(amount_musd, 2) AS amount_musd
                                   FROM {MFQ}.project_month_changes
                                   WHERE change_type = '{ct}'
                                     AND date_format(reporting_month, 'yyyy-MM') > '{month_a}'
                                     AND date_format(reporting_month, 'yyyy-MM') <= '{month_b}'
                                   ORDER BY abs(amount_musd) DESC NULLS LAST LIMIT 200"""),
                         hide_index=True, use_container_width=True)

# ---- 6. Upload a month -----------------------------------------------------------------------------------
FILE_PATTERNS = {"projects": re.compile(r"^synthetic_ifc_projects_.*\.csv$"),
                 "monitoring": re.compile(r"^synthetic_project_monitoring.*\.csv$")}
LANDING = f"/Volumes/{MFQ.replace('.', '/')}/landing/incoming"
JOB_ID = os.environ.get("IFC_MONTHLY_JOB_ID", "")

with tab_upload:
    st.write("Upload one month's source files. The pipeline checks them against the data contracts, certifies the "
             "month and refreshes the trends. Uploading again for a month that is already loaded **replaces only "
             "that month** (the earlier files stay in Raw for audit).")
    c1, c2 = st.columns([1, 2])
    month = c1.text_input("Reporting month (YYYY-MM)", placeholder="2026-11")
    files = c2.file_uploader("Projects and monitoring CSVs (synthetic_ifc_projects_*.csv, synthetic_project_monitoring*.csv)",
                             type="csv", accept_multiple_files=True)
    valid_month = bool(re.fullmatch(r"20\d\d-(0[1-9]|1[0-2])", month or ""))
    try:
        loaded = query(f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, source, source_file, rows_loaded,
                                  loaded_at, is_active FROM {MFQ}.ops_monthly_loads ORDER BY reporting_month DESC, loaded_at DESC""")
    except Exception:
        loaded = pd.DataFrame()
    if valid_month and len(loaded) and month in set(loaded["month"]):
        st.warning(f"{month} is already loaded. Uploading again replaces {month} with these files.")
    bad = [f.name for f in files or [] if not any(p.match(f.name) for p in FILE_PATTERNS.values())]
    if bad:
        st.error(f"Unrecognised file name(s): {', '.join(bad)}. Expected synthetic_ifc_projects_*.csv or "
                 "synthetic_project_monitoring*.csv.")
    if month and not valid_month:
        st.error("Month must look like 2026-11.")
    if not JOB_ID:
        st.info("Set the app resource **monthly-job** (the run_monthly_pipeline job) to run the pipeline from here.")
    if st.button("Upload and run pipeline", type="primary", disabled=not (valid_month and files and not bad)):
        from databricks.sdk import WorkspaceClient
        w = WorkspaceClient()
        with st.spinner("Uploading..."):
            for f in files:
                w.files.upload(f"{LANDING}/{month}/{f.name}", io.BytesIO(f.getvalue()), overwrite=True)
        st.success(f"Uploaded {len(files)} file(s) to incoming/{month}/.")
        if JOB_ID:
            run = w.jobs.run_now(job_id=int(JOB_ID))
            st.session_state["monthly_run_id"] = run.run_id
            st.success(f"Pipeline started (run {run.run_id}). It takes about 10–15 minutes per month.")

    st.subheader("Pipeline runs")
    if JOB_ID:
        from databricks.sdk import WorkspaceClient
        if st.button("Refresh status"):
            pass
        runs = WorkspaceClient().jobs.list_runs(job_id=int(JOB_ID), limit=5)
        st.dataframe(pd.DataFrame([{
            "run_id": r.run_id,
            "started": pd.to_datetime(r.start_time, unit="ms") if r.start_time else None,
            "state": (r.state.result_state or r.state.life_cycle_state).value if r.state else "",
            "message": r.state.state_message if r.state else "",
            "link": r.run_page_url} for r in runs]), hide_index=True, use_container_width=True)
    st.subheader("Loaded months")
    if len(loaded):
        st.dataframe(loaded, hide_index=True, use_container_width=True)
    try:
        st.subheader("Latest file checks (schema gate)")
        st.dataframe(query(f"""SELECT date_format(reporting_month, 'yyyy-MM') AS month, file_name, source, status, messages
                               FROM {MFQ}.ops_schema_gate_log ORDER BY checked_at DESC LIMIT 20"""),
                     hide_index=True, use_container_width=True)
    except Exception:
        pass
