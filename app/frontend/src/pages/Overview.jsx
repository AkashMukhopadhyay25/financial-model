import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { AskBar } from "../Genie.jsx";
import { ago, date, int, musd, pct } from "../format.js";
import { DataTable, DqTag, ErrorBox, EvidenceDrawer, Info, Loading, OkIcon, SplitBar, StatusTag, Stripe, Tag, useApi } from "../ui.jsx";

const STORIES = [
  { page: "portfolio", eyebrow: "WS1 · Portfolio analytics", color: "blue", q: "What does IFC's portfolio look like?", d: "Explore metrics and answer recurring questions in plain language." },
  { page: "risk", eyebrow: "WS2 · Integrated risk & exposure", color: "red", q: "Where is IFC exposed, and what are the potential losses?", d: "Join project and monitoring records to answer the two Board questions." },
  { page: "clients", eyebrow: "WS3 · Client intelligence + our agents", color: "green", q: "Which clients should IFC back, what if credit worsens, and where should new money go?", d: "Client recommendations, the stress-test agent and the capital allocation agent." },
  { page: "early-warning", eyebrow: "Early warning intelligence", color: "amber", q: "What could become a problem before it becomes Past Due?", d: "Flag emerging risk signals for human investigation." },
];

export default function Overview() {
  const { nav, openLibrary } = useApp();
  const { data, error, loading } = useApi("/api/overview");
  const [evidence, setEvidence] = useState(false);
  const [text, setText] = useState("");

  const route = (q) => {
    const t = q.trim();
    if (/^\/?investigate/i.test(t)) return nav("early-warning");
    if (/^\/?board/i.test(t)) return nav("briefing");
    nav("portfolio", { q: t.replace(/^\/portfolio question\s*/i, ""), t: Date.now() });
  };

  const k = data?.kpis;
  const a = data?.alerts || {};
  const maxAlert = Math.max(Number(k?.clients) || 0, 1); // alert bars = share of all clients
  const STATUS_COLOR = { Active: "#1f9d55", Pending: "#2f66f6", Closed: "#9aa1b3", Dropped: "#c9302c" };
  const BAND = { CONTINUE: ["Continue", "#1f9d55"], MONITOR: ["Monitor", "#2f66f6"], REDUCE_OR_REVIEW: ["Review", "#e29a12"] };
  const byStatus = (key) => ["Active", "Pending", "Closed", "Dropped"].map((st) => ({
    label: st, color: STATUS_COLOR[st], value: Number((data?.status_mix || []).find((x) => x.status === st)?.[key] || 0) }));
  const byBand = Object.entries(BAND).map(([b, [label, color]]) => ({
    label, color, value: Number((data?.client_bands || []).find((x) => x.band === b)?.clients || 0) }));
  return (
    <>
      <div className="page-head" style={{ marginTop: 22 }}>
        <div>
          <h1 className="title">Executive overview</h1>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => nav("briefing")}>Export / briefing</button>
          <button className="btn dark" onClick={() => nav("early-warning")}>Investigate an alert</button>
        </div>
      </div>

      <div id="ask" style={{ marginBottom: 14 }}>
        <AskBar
          value={text}
          onChange={setText}
          placeholder="Ask a portfolio question, investigate an alert or prepare a Board briefing"
          onAsk={route}
          variant="hero"
          extraChip={
            <>
              <button className="chip" onClick={() => document.querySelector("#ask input")?.focus()}>/portfolio question</button>
              <button className="chip" onClick={() => nav("early-warning")}>/investigate alert</button>
              <button className="chip" onClick={() => nav("briefing")}>/Board briefing</button>
              <button className="chip plain" onClick={() => openLibrary()}>Browse 30-question library</button>
            </>
          }
        />
      </div>
      {error && <ErrorBox error={error} />}
      {loading && <Loading />}
      {k && (
        <div className="grid g3">
          <Kpi label="Approved investment" tag={`As of ${date(k.reporting_date)}`} tagColor="blue" value={musd(k.approved_musd, { digits: 1 })} bar={<SplitBar segments={byStatus("approved_musd")} format={(v) => musd(v)} legend />}
               info={`Board-approved total, every status (A03, A08), as of ${date(k.reporting_date)}.`} onClick={() => setEvidence(true)} />
          <Kpi label="Projects" tag={`${int(k.active_projects)} Active`} tagColor="green" value={int(k.projects)} bar={<SplitBar segments={byStatus("projects")} legend />}
               info={`${int(k.active_projects)} Active. Counted by project URL (A01).`} onClick={() => nav("portfolio")} />
          <Kpi label="Clients" tag={`${int(byBand.find((b) => b.label === "Continue")?.value || 0)} strong · ${int(byBand.find((b) => b.label === "Review")?.value || 0)} to review`} tagColor="blue" value={int(k.clients)} bar={<SplitBar segments={byBand} legend />}
               info="Distinct clients with monitored projects, split by client band (A15)." onClick={() => nav("clients", { step: "directory" })} />
        </div>
      )}

      <Strengths />

      <div className="grid g3 mt">
        <div className="card">
          <div className="card-head">
            <h3>Priority risk alerts {k && <Info align="left" text={`Clients with early-warning signals (A22). Bars show the share of all ${int(k.clients)} clients. Separately, ${int(k.projects_needing_review)} projects carry data-quality flags (${int(k.projects_high_severity)} high); they stay in every total.`} />}</h3>
            <button className="icon-btn" aria-label="Open early warning" onClick={() => nav("early-warning")}>↗</button>
          </div>
          <AlertRow label="High priority" n={a.HIGH} max={maxAlert} color="var(--red)" />
          <AlertRow label="Requiring review" n={a.MEDIUM} max={maxAlert} color="var(--amber)" />
          <AlertRow label="Monitoring reminders" n={a.REVIEW} max={maxAlert} color="var(--blue)" />
        </div>
        <div className="card" style={{ background: "linear-gradient(180deg,#fff,#f6f8fc)" }}>
          <h3 style={{ marginBottom: 12 }}>Recent portfolio activity</h3>
          <div className="activity">
            {(data?.activity || []).map((x) => (
              <div key={x.label}>
                <OkIcon />
                <span>
                  {x.label}
                  <small>{ago(x.at)}</small>
                </span>
              </div>
            ))}
            {data && !data.activity?.length && <div className="muted small">No activity logged yet.</div>}
          </div>
        </div>
        <RiskCard r={data?.risk} pr={data?.portfolio_risk} onOpen={() => nav("risk")} />
      </div>

      <Spotlight />


      <div className="section-title" style={{ marginTop: 22 }}>One connected product story</div>
      <div className="grid g4">
        {STORIES.map((s) => (
          <div key={s.page} className="card story" onClick={() => nav(s.page)}>
            <div className={`eyebrow ${s.color}`}>{s.eyebrow}</div>
            <h4>{s.q}</h4>
          </div>
        ))}
      </div>
      {evidence && <EvidenceDrawer items={data.evidence} onClose={() => setEvidence(false)} />}
    </>
  );
}

function Kpi({ label, tag, tagColor, value, info, onClick, bar }) {
  return (
    <div className="card" style={{ cursor: "pointer" }} onClick={onClick}>
      <div className="kpi-label">
        <span>{label} <Info text={info} align="left" /></span> <span className={`tag ${tagColor}`}>{tag}</span>
      </div>
      <div className="kpi-value">{value}</div>
      {bar}
    </div>
  );
}

function AlertRow({ label, n, max, color }) {
  return (
    <div className="alert-row">
      <div className="top">
        <span>{label}</span>
        <b>{n ?? "–"}</b>
      </div>
      <Stripe value={(n || 0) / max} color={color} />
    </div>
  );
}

// Credit risk at a glance: the WS2 Board answer (expected credit loss and the exposure behind it). Opens Risk & exposure.
function RiskCard({ r, pr, onOpen }) {
  // The bar is the disbursed exposure; its solid red part is the expected credit loss in the headline.
  const pd = r?.past_due_disbursed_musd || 0, wl = r?.watchlist_disbursed_musd || 0, ecl = r?.expected_credit_loss_musd || 0;
  const exposure = pd + wl;
  const segs = [
    { cls: "ecl", v: ecl, t: `Expected loss ${musd(ecl)}: 60% of Past Due disbursed` },
    { cls: "pd", v: Math.max(0, pd - ecl), t: `Rest of Past Due ${musd(pd - ecl)}: disbursed, not expected to be lost` },
    { cls: "wl", v: wl, t: `Watchlist ${musd(wl)}: disbursed, no provision` },
  ];
  return (
    <div className="copilot risk-card" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Tag>Credit risk at a glance</Tag>
          <span className="small" style={{ opacity: 0.85 }}>Open ↗</span>
        </div>
        <div className="risk-label">Category A expected credit loss</div>
        <div className="risk-value">{r ? musd(ecl) : "…"}</div>
        <div className="risk-sub">{exposure ? `${Math.round((100 * ecl) / exposure)}% of ${musd(exposure)} disbursed exposure` : ""}</div>
      </div>
      <div>
        <div className="risk-split">
          {segs.map((x) => <div key={x.cls} style={{ flex: x.v || 0.001 }} className={x.cls} title={x.t} />)}
        </div>
        <div className="risk-legend">
          <span title={segs[0].t}><i className="ecl" />Loss<em className="amt">&nbsp;{musd(ecl)}</em></span>
          <span title={segs[1].t}><i className="pd" />Past Due rest<em className="amt">&nbsp;{musd(pd - ecl)}</em></span>
          <span title={segs[2].t}><i className="wl" />Watchlist<em className="amt">&nbsp;{musd(wl)}</em></span>
        </div>
        <div className="risk-foot">
          {r ? `${int(r.projects)} Category A projects · ${int(r.clients)} clients` : ""}
          {pr && <div style={{ marginTop: 4, opacity: 0.85 }}>Whole portfolio: {musd(pr.expected_credit_loss_musd)} ECL on {int(pr.past_due_projects)} Past Due projects (A11)</div>}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- what is going well (same rigour as the risk views)
function Strengths() {
  const { nav } = useApp();
  const { data: s } = useApi("/api/strengths");
  const [sql, setSql] = useState(false);
  if (!s) return null;
  const rec = s.record_fy, latest = s.latest_fy;
  const tiles = [
    { v: pct(s.performing_projects / s.active_projects), l: "of Active projects performing",
      f: `${int(s.performing_projects)} of ${int(s.active_projects)} · ${pct(s.performing_exposure_share)} of current exposure`, go: () => nav("portfolio") },
    { v: pct(s.completed_projects / s.closed_projects), l: "of closed projects completed",
      f: `${int(s.completed_projects)} of ${int(s.closed_projects)} met their obligations · ${pct(s.completed_disbursed_share)} of closed disbursed` },
    { v: int(s.climate_projects), l: "climate-related projects", f: `${musd(s.climate_approved_musd, { digits: 1 })} approved` },
    { v: `${(s.renewable_capacity_mw / 1000).toFixed(1)} GW`, l: "new renewable capacity", f: `${int(s.renewable_projects)} generation projects (A13)` },
    { v: int(s.msme_projects), l: "small-business finance projects", f: `MSME lending through financial institutions (A14)` },
    rec && { v: musd(rec.approved_musd, { digits: 1 }), l: `approved in FY${rec.approval_fy}, a record year`,
      f: `${int(rec.projects)} projects${latest && latest.approval_fy !== rec.approval_fy ? ` · FY${latest.approval_fy}: ${musd(latest.approved_musd, { digits: 1 })}` : ""} · ${int(s.countries)} countries` },
  ].filter(Boolean);
  return (
    <div className="card mt strengths">
      <div className="card-head">
        <div>
          <h3>What is going well</h3>
          <div className="card-sub">Same certified data and definitions as the risk views below</div>
        </div>
        <button className="btn small" onClick={() => setSql(true)}>Evidence / SQL</button>
      </div>
      <div className="strength-grid">
        {tiles.map((t) => (
          <div key={t.l} className={`strength ${t.go ? "clickable" : ""}`} onClick={t.go}>
            <div className="sv">{t.v}</div>
            <div className="sl">{t.l}</div>
            <div className="sf">{t.f}</div>
          </div>
        ))}
      </div>
      {sql && <EvidenceDrawer items={s.sql} note="Every strength is computed from certified_investment_portfolio with the same definitions as the risk figures." onClose={() => setSql(false)} />}
    </div>
  );
}

// ---------------------------------------------------------------- project spotlight (click a row for the full project)
const SPOT_TABS = [
  ["largest", "Largest Active"], ["performing", "Strong performers"], ["recent", "Recently approved"], ["attention", "Needs attention"],
];

function Spotlight() {
  const { openProject } = useApp();
  const [view, setView] = useState("largest");
  const { data, error, loading } = useApi(`/api/projects/spotlight?view=${view}&limit=8`);
  return (
    <div className="card mt">
      <div className="card-head">
        <div>
          <h3>Project spotlight</h3>
          <div className="card-sub">{data ? `${data.title} · ${int(data.total)} projects · click a project for its full record` : "Projects behind the numbers"}</div>
        </div>
        <div className="toggle">
          {SPOT_TABS.map(([id, label]) => (
            <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)}>{label}</button>
          ))}
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      {loading && !data && <Loading />}
      {data && (
        <DataTable
          rows={data.rows}
          onRowClick={(r) => openProject(r.project_url)}
          columns={[
            { key: "project_name", label: "Project", strong: true },
            { key: "client_name", label: "Client" },
            { key: "country", label: "Country" },
            { key: "industry", label: "Industry" },
            { key: "performance_status", label: "Status", render: (v, r) => <StatusTag value={v || r.status} /> },
            { key: "internal_risk_rating", label: "Rating", num: true },
            { key: view === "recent" ? "approval_date" : "current_exposure_musd", label: view === "recent" ? "Approved on" : "Exposure", num: view !== "recent",
              render: (v) => (view === "recent" ? date(v) : musd(v)) },
            { key: "approved_musd", label: "Approved", num: true, render: (v) => musd(v) },
            { key: "needs_review", label: "Data quality", render: (v, r) => <DqTag needs={v} severity={r.dq_max_severity} ids={r.dq_flag_ids} messages={r.dq_messages} /> },
          ]}
        />
      )}
    </div>
  );
}
