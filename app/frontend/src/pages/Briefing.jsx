import React from "react";
import { useApp } from "../App.jsx";
import { date, int, musd, musdFull } from "../format.js";
import { ErrorBox, Info, Loading, SplitBar, Tag, useApi } from "../ui.jsx";
import { ExposureBreakdown } from "./Risk.jsx";

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

const STATUS_COLOR = { Active: "#1f9d55", Pending: "#2f66f6", Closed: "#9aa1b3", Dropped: "#c9302c" };
const SIGNAL_COLOR = {
  "Multiple Watchlist projects": "amber", "Internal risk ratings 5-6": "red", "Long time since last review": "blue",
  "Existing Past Due projects": "red", "Concentration in one country": "teal",
};

function Section({ n, title, sub, link, onLink, children }) {
  return (
    <div className="card mt brief-sec">
      <div className="brief-head">
        <span className="brief-n">{n}</span>
        <div>
          <h2>{title}</h2>
          {sub && <div className="card-sub">{sub}</div>}
        </div>
        {link && <button className="link no-print" style={{ marginLeft: "auto" }} onClick={onLink}>{link} →</button>}
      </div>
      {children}
    </div>
  );
}

function Brief({ d, nav }) {
  const k = d.overview.kpis;
  const by = Object.fromEntries(d.risk.summary.map((r) => [r.status_label, r]));
  const tot = by.TOTAL || {}, pd = by["Past Due"] || {}, wl = by.Watchlist || {};
  const pdD = pd.disbursed_capital_tied_up_musd || 0, wlD = wl.disbursed_capital_tied_up_musd || 0;
  const rate = pdD ? (tot.expected_credit_loss_musd || 0) / pdD : 0.6;
  const statuses = ["Active", "Pending", "Closed", "Dropped"].map((st) => ({ st, ...(d.overview.status_mix.find((x) => x.status === st) || {}) }));
  const maxOwner = Math.max(1, ...d.review_owners.map((o) => o.projects));
  return (
    <div className="brief">
      <div className="grid g4">
        <Stat label="Approved investment" value={musd(k.approved_musd, { digits: 1 })}
              bar={<SplitBar format={(v) => musd(v)} segments={statuses.map((x) => ({ label: x.st, value: x.approved_musd || 0, color: STATUS_COLOR[x.st] }))} />}
              note={`${int(k.projects)} projects, all statuses`} />
        <Stat label="Active projects" value={int(k.active_projects)}
              bar={<SplitBar segments={[{ label: "Active", value: k.active_projects, color: "#1f9d55" }, { label: "Other", value: k.projects - k.active_projects, color: "#d5d9e3" }]} />}
              note={`${int(k.clients)} clients`} />
        <Stat label="Category A in distress" value={int(tot.projects)}
              bar={<SplitBar segments={[{ label: "Past Due", value: pd.projects, color: "#c9302c" }, { label: "Watchlist", value: wl.projects, color: "#e29a12" }]} />}
              note={`${int(pd.projects)} Past Due · ${int(wl.projects)} Watchlist`} />
        <Stat label="Category A expected credit loss" value={musd(tot.expected_credit_loss_musd)} dark
              note={`${Math.round(rate * 100)}% of ${musd(pdD)} Past Due disbursed · whole portfolio ${musd(d.overview.portfolio_risk?.expected_credit_loss_musd)}`} />
      </div>

      <Section n="1" title="Portfolio at a glance" sub={`As of ${date(k.reporting_date)} · board-approved, every status`} link="Portfolio analytics" onLink={() => nav("portfolio")}>
        <SplitBar format={(v) => musd(v)} height={12} segments={statuses.map((x) => ({ label: x.st, value: x.approved_musd || 0, color: STATUS_COLOR[x.st] }))} />
        <div className="grid g4 mt">
          {statuses.map((x) => (
            <div key={x.st} className="mini">
              <div className="k"><span className="dot" style={{ background: STATUS_COLOR[x.st], marginRight: 6 }} />{x.st}</div>
              <div className="v big">{musd(x.approved_musd)}</div>
              <div className="small muted">{int(x.projects)} projects</div>
            </div>
          ))}
        </div>
      </Section>

      <Section n="2" title="Board questions: Category A risk" sub={`${int(tot.projects)} projects Past Due or on the Watchlist · ${int(tot.clients)} clients · ${musd(tot.approved_musd)} approved`}
               link="Risk & exposure" onLink={() => nav("risk")}>
        <ExposureBreakdown bare pd={pdD} wl={wlD} ecl={tot.expected_credit_loss_musd || 0}
                           undisbursed={tot.undisbursed_commitment_musd || 0} approved={tot.approved_musd || 0} rate={rate} />
        <div className="chips" style={{ marginTop: 12 }}>
          {d.risk.checks.map((c) => <Tag key={c.name} color={c.ok ? "green" : "amber"}>{c.ok ? "✓" : "!"} {c.name}</Tag>)}
        </div>
      </Section>

      <Section n="3" title="Client recommendations" sub="For Credit Risk Committee review" link="Client intelligence" onLink={() => nav("clients")}>
        <div className="grid g4">
          {d.recommendations.map((r) => {
            const cont = r.recommendation === "CONTINUE";
            return (
              <div key={r.client_id} className="brief-rec">
                <Tag color={cont ? "green" : "red"} caps>{cont ? "Continue to invest" : "Reduce / review"}</Tag>
                <div className="brief-rec-name">{r.client_name}</div>
                <div className="small muted">{r.primary_industry} · {r.primary_region}</div>
                <div className="brief-rec-amt">{musd(r.exposure_affected_musd)} <Info align="left" text={`${r.evidence_summary}. ${r.suggested_action}`} /></div>
                <SplitBar format={(v) => musd(v)} segments={[
                  { label: "Disbursed", value: r.current_disbursed_exposure_musd, color: "#2f66f6" },
                  { label: "Undisbursed", value: r.undisbursed_commitment_musd, color: "#16a389" },
                ]} />
                {r.expected_credit_loss_musd > 0 && <div className="mt"><Tag color="red">ECL {musd(r.expected_credit_loss_musd)}</Tag></div>}
              </div>
            );
          })}
        </div>
      </Section>

      <Section n="4" title="Early warning: highest-priority clients" sub="Risk signals for human investigation, not predictions of default" link="Early warning" onLink={() => nav("early-warning")}>
        <div className="brief-ew">
          {d.early_warning.map((e) => (
            <div key={e.client_id} className="brief-ew-row">
              <div className="brief-ew-name">{e.client_name}</div>
              <div className="chips" style={{ marginTop: 0 }}>
                {String(e.triggered_by || "").split("; ").filter(Boolean).map((t) => <Tag key={t} color={SIGNAL_COLOR[t] || "grey"}>{t}</Tag>)}
              </div>
              <div className="brief-ew-amt">{musd(e.exposure_affected_musd)}</div>
            </div>
          ))}
        </div>
        <div className="small muted mt">Suggested action for all: {d.early_warning[0]?.suggested_action || "–"}.</div>
      </Section>

      <Section n="5" title="Data quality" sub={`${int(k.projects_needing_review)} projects flagged (${int(k.projects_high_severity)} high) · included in every figure · routed to owners`}>
        <div className="brief-owners">
          {d.review_owners.map((o) => (
            <div key={o.owner} className="brief-owner">
              <span>{o.owner}</span>
              <div className="brief-owner-bar"><div style={{ width: `${(100 * o.projects) / maxOwner}%` }} /></div>
              <b>{int(o.projects)}</b>
            </div>
          ))}
        </div>
        <details className="mt">
          <summary style={{ cursor: "pointer", fontWeight: 600, fontSize: 13 }}>Assumptions applied ({d.assumptions.length})</summary>
          <ul>
            {d.assumptions.map((a) => (
              <li key={a.assumption_id}><b>{a.topic}.</b> {a.statement}</li>
            ))}
          </ul>
        </details>
      </Section>
    </div>
  );
}

const Stat = ({ label, value, note, bar, dark }) => (
  <div className={dark ? "copilot" : "card"} style={dark ? { minHeight: 0, cursor: "default" } : undefined}>
    <div className="kpi-label" style={dark ? { color: "#fff", opacity: 0.9 } : undefined}>{label}</div>
    <div className="kpi-value" style={{ fontSize: 34 }}>{value}</div>
    {bar}
    <div className="kpi-foot" style={dark ? { color: "#fff", opacity: 0.85 } : { marginTop: 8 }}>{note}</div>
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
    `- ${k.projects} projects, ${musdFull(k.approved_musd)} approved by the Board (all statuses); ${k.active_projects} Active; ${k.clients} clients.`, ``,
    `## 2. Category A risk (WS2)`,
    `- ${t.projects} Category A projects are Past Due (${by["Past Due"]?.projects}) or on the Watchlist (${by.Watchlist?.projects}), across ${t.clients} clients, ${musdFull(t.approved_musd)} approved.`,
    `- ${musdFull(t.disbursed_capital_tied_up_musd)} disbursed capital tied up; recommended provision for these Category A projects ${musdFull(t.expected_credit_loss_musd)} (60% of Past Due disbursed).`,
    `- For context, expected credit loss on the whole portfolio is ${musdFull(d.overview.portfolio_risk?.expected_credit_loss_musd)} (${d.overview.portfolio_risk?.past_due_projects} Past Due projects, A11).`, ``,
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
