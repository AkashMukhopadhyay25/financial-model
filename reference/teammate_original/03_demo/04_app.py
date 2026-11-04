"""CFO Portfolio Advisor: Databricks App (Streamlit) for IFC's CFO Office.

Tabs
  1. Ask the Advisor   - chat with the CFO Decision Advisor (agent + Genie); every answer shows evidence and review status
  2. Board risk view   - WS2: Category A Past Due / Watchlist exposure and loss provision
  3. Client decisions  - WS3: scorecard by band, drill-down to project evidence, the four recommendations
  4. Trust & quality   - data-quality checks, assumptions, recent agent answers awaiting review

Deploy: Compute -> Apps -> Create app -> source code path = the team folder (app.yaml sits there).
Configuration via app.yaml environment variables; credentials come from the app's service principal.
"""
import os
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


def num(df, cols):
    for c in cols:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


FQ = cfo_agent.FQ
st.title("CFO Portfolio Advisor")
st.caption("IFC CFO Office · governed data on Databricks · every figure traceable to its SQL · amounts in USD millions")

tab_ask, tab_board, tab_clients, tab_trust = st.tabs(["Ask the Advisor", "Board risk view", "Client decisions", "Trust & quality"])

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
            st.markdown(m["content"])
    prompt = st.chat_input("e.g. Why is this client flagged? Show me the evidence.") or st.session_state.pop("pending", None)
    if prompt:
        st.session_state["chat"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Planning, querying governed data, checking evidence..."):
                result = core().run([{"role": m["role"], "content": m["content"]} for m in st.session_state["chat"]])
            badge = {"VALIDATED": "🟢", "REVIEW_RECOMMENDED": "🟡", "HUMAN_REVIEW_REQUIRED": "🔴"}[result["review_status"]]
            st.markdown(f"{badge} **{result['review_status'].replace('_', ' ').title()}**")
            st.markdown(result["answer"])
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
                    st.markdown(f"**{r.client_name}** ({r.client_id}) · exposure affected **${r.exposure_affected_musd:,.0f}M** "
                                f"(disbursed ${r.current_disbursed_exposure_musd:,.0f}M + undisbursed ${r.undisbursed_commitment_musd:,.0f}M)  \n"
                                f"{r.evidence_summary}  \n_{r.suggested_action}_")
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
