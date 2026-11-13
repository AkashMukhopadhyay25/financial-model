import React from "react";
import { useApp } from "../App.jsx";
import { date, int, musd, musdFull } from "../format.js";
import { DataTable, ErrorBox, Loading, Tag, useApi } from "../ui.jsx";

// Board briefing: every number below is read live from the certified tables, so the briefing never drifts from the app.
export default function Briefing() {
  const { nav, openLibrary } = useApp();
  const { data, error, loading } = useApi("/api/briefing");
  const md = data ? toMarkdown(data) : "";
  const download = () => {
    const blob = new Blob([md], { type: "text/markdown" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `ifc_board_briefing_${data.overview.kpis.reporting_date}.md`;
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <>
      <div className="eyebrow blue">Board briefing</div>
      <div className="page-head">
        <div>
          <h1 className="title">Board briefing</h1>
          <div className="subtitle">Draft for the CFO Office · every figure traceable to certified SQL</div>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => openLibrary()}>Certified answers</button>
          <button className="btn" onClick={download} disabled={!data}>Download (.md)</button>
          <button className="btn dark" onClick={() => window.print()} disabled={!data}>Print / save as PDF</button>
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      {loading && <Loading />}
      {data && <Brief d={data} nav={nav} />}
    </>
  );
}

function Brief({ d, nav }) {
  const k = d.overview.kpis;
  const by = Object.fromEntries(d.risk.summary.map((r) => [r.status_label, r]));
  const tot = by.TOTAL || {};
  return (
    <div className="brief">
      <div className="grid g4">
        <Stat label="Approved investment" value={musd(k.approved_musd, { digits: 1 })} note={`${int(k.projects)} projects, all statuses`} />
        <Stat label="Active projects" value={int(k.active_projects)} note={`${int(k.clients)} clients`} />
        <Stat label="Category A in distress" value={int(tot.projects)} note={`${musd(tot.disbursed_capital_tied_up_musd)} disbursed`} />
        <Stat label="Expected credit loss" value={musd(tot.expected_credit_loss_musd)} note="60% of Past Due disbursed (A11)" />
      </div>

      <div className="card mt">
        <h2>1. Portfolio at a glance</h2>
        <p>
          As of the reporting date {date(k.reporting_date)}, IFC's portfolio holds <b>{int(k.projects)}</b> projects with{" "}
          <b>{musdFull(k.approved_musd)}</b> approved by the Board (every status, Dropped included, A03). {int(k.active_projects)} projects are Active.
        </p>
        <DataTable rows={d.overview.status_mix} columns={[
          { key: "status", label: "Status" }, { key: "projects", label: "Projects", num: true },
          { key: "approved_musd", label: "Approved", num: true, render: (v) => musdFull(v) },
        ]} />
        <button className="link mt no-print" onClick={() => nav("portfolio")}>Explore in Portfolio analytics →</button>
      </div>

      <div className="card mt">
        <h2>2. Board questions: Category A risk (WS2)</h2>
        <ul>
          <li><b>{int(tot.projects)}</b> Category A projects are Past Due ({int(by["Past Due"]?.projects)}) or on the Watchlist ({int(by.Watchlist?.projects)}), across {int(tot.clients)} clients, with {musdFull(tot.approved_musd)} approved.</li>
          <li><b>{musdFull(tot.disbursed_capital_tied_up_musd)}</b> of disbursed capital is tied up in them: {musdFull(by["Past Due"]?.disbursed_capital_tied_up_musd)} Past Due and {musdFull(by.Watchlist?.disbursed_capital_tied_up_musd)} Watchlist.</li>
          <li>Recommended provision on the Past Due projects: <b>{musdFull(tot.expected_credit_loss_musd)}</b>. A further {musdFull(tot.undisbursed_commitment_musd)} is approved but undisbursed.</li>
        </ul>
        <div className="small muted">Checks: {d.risk.checks.map((c) => `${c.name} ${c.ok ? "✓" : "✗"}`).join(" · ")}</div>
        <button className="link mt no-print" onClick={() => nav("risk")}>Open Risk &amp; exposure →</button>
      </div>

      <div className="card mt">
        <h2>3. Client recommendations (WS3) — for Credit Risk Committee review</h2>
        {d.recommendations.map((r) => (
          <div key={r.client_id} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Tag color={r.recommendation === "CONTINUE" ? "green" : "red"} caps>{r.recommendation === "CONTINUE" ? "Continue to invest" : "Reduce / review"}</Tag>
              <b>{r.client_name}</b> <span className="small muted">{r.client_id} · {r.primary_industry}, {r.primary_region}</span>
            </div>
            <p style={{ margin: "6px 0 0" }}>
              Exposure affected {musdFull(r.exposure_affected_musd)} (disbursed {musdFull(r.current_disbursed_exposure_musd)} + undisbursed {musdFull(r.undisbursed_commitment_musd)}).
              Evidence: {r.evidence_summary}. {r.suggested_action}
            </p>
          </div>
        ))}
        <button className="link no-print" onClick={() => nav("clients")}>Open Client intelligence →</button>
      </div>

      <div className="card mt">
        <h2>4. Early warning: highest-priority clients</h2>
        <p className="small muted" style={{ marginTop: 0 }}>Risk signals for human investigation, not predictions of default (A22).</p>
        <DataTable rows={d.early_warning} columns={[
          { key: "client_name", label: "Client", strong: true }, { key: "triggered_by", label: "Signals" },
          { key: "exposure_affected_musd", label: "Exposure affected", num: true, render: (v) => musd(v) },
          { key: "suggested_action", label: "Suggested action" },
        ]} />
      </div>

      <div className="card mt">
        <h2>5. Data quality and assumptions</h2>
        <p>
          {int(k.projects_needing_review)} projects carry open data-quality flags ({int(k.projects_high_severity)} high severity). They are
          included in every figure and routed to their owners:
        </p>
        <DataTable rows={d.review_owners} columns={[{ key: "owner", label: "Owner" }, { key: "projects", label: "Projects flagged", num: true }]} />
        <details className="mt">
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>Assumptions applied ({d.assumptions.length})</summary>
          <ul>
            {d.assumptions.map((a) => (
              <li key={a.assumption_id}><b>{a.assumption_id} {a.topic}.</b> {a.statement}</li>
            ))}
          </ul>
        </details>
      </div>
    </div>
  );
}

const Stat = ({ label, value, note }) => (
  <div className="card">
    <div className="kpi-label">{label}</div>
    <div className="kpi-value" style={{ fontSize: 34 }}>{value}</div>
    <div className="kpi-foot">{note}</div>
  </div>
);

function toMarkdown(d) {
  const k = d.overview.kpis;
  const by = Object.fromEntries(d.risk.summary.map((r) => [r.status_label, r]));
  const t = by.TOTAL || {};
  const L = [
    `# IFC Board briefing (draft)`, ``,
    `*Reporting date ${k.reporting_date}. Amounts in USD millions. Every figure is read from the certified tables in Unity Catalog.*`, ``,
    `## 1. Portfolio at a glance`,
    `- ${k.projects} projects, ${musdFull(k.approved_musd)} approved by the Board (all statuses, A03); ${k.active_projects} Active; ${k.clients} clients.`, ``,
    `## 2. Category A risk (WS2)`,
    `- ${t.projects} Category A projects are Past Due (${by["Past Due"]?.projects}) or on the Watchlist (${by.Watchlist?.projects}), across ${t.clients} clients, ${musdFull(t.approved_musd)} approved.`,
    `- ${musdFull(t.disbursed_capital_tied_up_musd)} disbursed capital tied up; recommended provision ${musdFull(t.expected_credit_loss_musd)} (60% of Past Due disbursed, A11).`, ``,
    `## 3. Client recommendations (WS3) — for Credit Risk Committee review`,
    ...d.recommendations.map((r) => `- **${r.recommendation === "CONTINUE" ? "Continue to invest" : "Reduce / review"}: ${r.client_name} (${r.client_id})** — exposure affected ${musdFull(r.exposure_affected_musd)}. ${r.evidence_summary}. ${r.suggested_action}`),
    ``, `## 4. Early warning (highest priority)`,
    ...d.early_warning.map((e) => `- ${e.client_name}: ${e.triggered_by}. ${e.suggested_action}.`),
    ``, `## 5. Data quality`,
    `- ${k.projects_needing_review} projects carry open data-quality flags (${k.projects_high_severity} high); included in every figure.`,
    ...d.review_owners.map((o) => `  - ${o.owner}: ${o.projects}`),
    ``, `## Assumptions`, ...d.assumptions.map((a) => `- ${a.assumption_id} ${a.topic}: ${a.statement}`),
  ];
  return L.join("\n");
}
