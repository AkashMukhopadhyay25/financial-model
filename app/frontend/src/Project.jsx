import React from "react";
import { createPortal } from "react-dom";
import { date, int, musd, pct } from "./format.js";
import { Drawer, ErrorBox, Loading, SqlBlock, SplitBar, StatusTag, Tag, useApi } from "./ui.jsx";

// Project detail: one project from certified_investment_portfolio, opened from anywhere via useApp().openProject(url).
// Lifecycle, monitoring, amounts, what the description says, and every data-quality flag in plain words.
export function ProjectDrawer({ url, onClose, onOpen }) {
  const { data, error, loading } = useApi(`/api/projects/detail?url=${encodeURIComponent(url)}`, [url]);
  const p = data?.project;
  return createPortal(
    <Drawer title={p ? p.project_name : "Project"} onClose={onClose}>
      {error && <ErrorBox error={error} />}
      {loading && <Loading label="Loading the project…" />}
      {p && <Body p={p} others={data.client_projects} sql={data.sql} onOpen={onOpen} />}
    </Drawer>,
    document.body,
  );
}

function Body({ p, others, sql, onOpen }) {
  const disbursedShare = p.total_approved_musd ? (p.disbursed_musd || 0) / p.total_approved_musd : 0;
  const steps = [
    ["Disclosed", p.date_disclosed],
    ["Board approval", p.approval_date || (p.projected_board_date ? `${p.projected_board_date} (projected)` : null)],
    ["Signed", p.signed_date],
    ["First disbursement", p.invested_date],
  ];
  const products = [
    ["Loan", p.amt_loan_musd], ["Equity", p.amt_equity_musd], ["Guarantee", p.amt_guarantee_musd], ["Risk management", p.amt_risk_mgmt_musd],
  ].filter(([, v]) => v);
  return (
    <>
      <div className="small muted" style={{ marginTop: -6 }}>
        #{p.project_number} · {p.client_name || "No monitored client"} · {p.country} · {p.region} · {p.industry}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", margin: "10px 0 14px" }}>
        <StatusTag value={p.status} />
        {p.performance_status && <StatusTag value={p.performance_status} />}
        {p.internal_risk_rating && <Tag color={p.internal_risk_rating >= 5 ? "red" : p.internal_risk_rating >= 3 ? "amber" : "green"}>Risk rating {p.internal_risk_rating}/6</Tag>}
        <Tag color={p.environmental_category === "A" ? "red" : "grey"}>E&amp;S category {p.environmental_category}</Tag>
        {p.is_climate_related && <Tag color="green">Climate-related</Tag>}
        {p.is_new_renewable_generation && <Tag color="green">New renewable generation{p.new_capacity_mw ? ` · ${int(p.new_capacity_mw)} MW` : ""}</Tag>}
        {p.is_msme_financing && <Tag color="blue">Small-business finance{p.msme_target_group ? ` · ${p.msme_target_group}` : ""}</Tag>}
      </div>

      <div className="mini-grid" style={{ gridTemplateColumns: "repeat(3, minmax(0,1fr))" }}>
        <div className="mini"><div className="k">Approved (Board)</div><div className="v big">{musd(p.total_approved_musd)}</div></div>
        <div className="mini"><div className="k">Disbursed</div><div className="v big">{p.disbursed_musd == null ? "–" : musd(p.disbursed_musd)}</div></div>
        <div className="mini"><div className="k">{p.status === "Active" ? "Undisbursed commitment" : "Expected credit loss"}</div>
          <div className="v big">{musd(p.status === "Active" ? p.undisbursed_commitment_musd : p.expected_credit_loss_musd)}</div></div>
      </div>
      {p.disbursed_musd != null && (
        <div className="mt">
          <SplitBar format={(v) => musd(v)} legend segments={[
            { label: "Disbursed", value: p.disbursed_musd || 0, color: "#2f66f6" },
            { label: "Not yet disbursed", value: Math.max(0, (p.total_approved_musd || 0) - (p.disbursed_musd || 0)), color: "#d5d9e3" },
          ]} />
        </div>
      )}
      {p.expected_credit_loss_musd > 0 && p.status === "Active" && (
        <div className="small mt" style={{ color: "var(--red)" }}>Expected credit loss {musd(p.expected_credit_loss_musd)}: Past Due, 60% of disbursed (A11).</div>
      )}

      <h4 className="drawer-h">Lifecycle</h4>
      <div className="timeline">
        {steps.map(([label, d]) => (
          <div key={label} className={d ? "done" : ""}>
            <i />
            <span><b>{label}</b><small>{d ? (String(d).includes("projected") ? d : date(d)) : "not yet"}</small></span>
          </div>
        ))}
      </div>
      <div className="small muted">
        {p.days_approval_to_signing != null && `Approval to signing ${int(p.days_approval_to_signing)} days. `}
        {p.days_signing_to_investment != null && `Signing to first disbursement ${int(p.days_signing_to_investment)} days. `}
        {p.days_since_last_review != null && `Last monitoring review ${int(p.days_since_last_review)} days ago. `}
        Record as of {date(p.as_of_date)}.
      </div>

      {products.length > 0 && (
        <>
          <h4 className="drawer-h">Products</h4>
          <SplitBar format={(v) => musd(v)} legend segments={products.map(([label, value], i) => ({ label, value, color: ["#2f66f6", "#7c5cff", "#16a394", "#e29a12"][i] }))} />
          {Math.abs(p.alloc_gap_musd || 0) > 0.01 && (
            <div className="small muted mt">Products add up to {musd(p.total_approved_musd - p.alloc_gap_musd)}, {musd(Math.abs(p.alloc_gap_musd))} {p.alloc_gap_musd > 0 ? "below" : "above"} the approved amount.</div>
          )}
        </>
      )}

      <h4 className="drawer-h">Data quality</h4>
      {p.dq_flags.length ? (
        <>
          <div className="small muted" style={{ marginBottom: 6 }}>
            {p.dq_flags.length} open {p.dq_flags.length === 1 ? "issue" : "issues"} ({p.dq_max_severity}) · owner: {p.review_owners} · the project stays in every figure.
          </div>
          {p.dq_flags.map((f, i) => (
            <div key={i} className="dq-line"><Tag color={p.dq_max_severity === "high" ? "red" : "amber"}>{f.id || "flag"}</Tag><span>{f.message}</span></div>
          ))}
        </>
      ) : <div className="small"><Tag color="green">Clean</Tag> No open data-quality issues.</div>}
      {p.text_attributes_need_review && <div className="small mt"><Tag color="amber">Text review</Tag> {p.text_review_reason}</div>}

      {p.project_description && (
        <>
          <h4 className="drawer-h">Description</h4>
          <p className="small" style={{ lineHeight: 1.55 }}>{p.project_description}</p>
          {p.described_product && <div className="small muted">Main product named in the description: {p.described_product}</div>}
        </>
      )}

      {others?.length > 0 && (
        <>
          <h4 className="drawer-h">Other projects of {p.client_name}</h4>
          {others.map((o) => (
            <div key={o.project_url} className="dq-line" style={{ cursor: "pointer" }} onClick={() => onOpen(o.project_url)}>
              <StatusTag value={o.performance_status || o.status} /><span style={{ flex: 1 }}>{o.project_name}</span><b>{musd(o.approved_musd)}</b>
            </div>
          ))}
        </>
      )}

      <details className="mt small">
        <summary>SQL behind this view</summary>
        <SqlBlock sql={sql} />
      </details>
      <div className="small muted mt"><a href={p.project_url} target="_blank" rel="noreferrer">Project disclosure page ↗</a></div>
    </>
  );
}
