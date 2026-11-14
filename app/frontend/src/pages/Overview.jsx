import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { AskBar } from "../Genie.jsx";
import { ago, date, int, musd } from "../format.js";
import { ErrorBox, EvidenceDrawer, Info, Loading, OkIcon, Stripe, Tag, useApi } from "../ui.jsx";

const STORIES = [
  { page: "portfolio", eyebrow: "WS1 · Portfolio analytics", color: "blue", q: "What does IFC's portfolio look like?", d: "Explore metrics and answer recurring questions in plain language." },
  { page: "risk", eyebrow: "WS2 · Integrated risk & exposure", color: "red", q: "Where is IFC exposed, and what are the potential losses?", d: "Join project and monitoring records to answer the two Board questions." },
  { page: "clients", eyebrow: "WS3 · Client intelligence", color: "green", q: "Which client relationships should IFC prioritize or reconsider?", d: "Support client recommendations and quantify affected exposure." },
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
  const maxAlert = Math.max(a.HIGH || 0, a.MEDIUM || 0, a.REVIEW || 0, 1);
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
          <Kpi label="Approved investment" tag="Portfolio snapshot" tagColor="blue" value={musd(k.approved_musd, { digits: 1 })} color="var(--blue)"
               info={`Board-approved total, every status (A03, A08), as of ${date(k.reporting_date)}.`} onClick={() => setEvidence(true)} />
          <Kpi label="Projects" tag="Portfolio snapshot" tagColor="green" value={int(k.projects)} color="var(--green)"
               info={`${int(k.active_projects)} Active. Counted by project URL (A01).`} onClick={() => nav("portfolio")} />
          <Kpi label="Clients" tag="Portfolio snapshot" tagColor="pink" value={int(k.clients)} color="var(--pink)"
               info="Distinct clients with monitored projects." onClick={() => nav("clients", { step: "directory" })} />
        </div>
      )}

      <div className="grid g3 mt">
        <div className="card">
          <div className="card-head">
            <h3>Priority risk alerts {k && <Info align="left" text={`Clients with early-warning signals (A22). Separately, ${int(k.projects_needing_review)} projects carry data-quality flags (${int(k.projects_high_severity)} high); they stay in every total.`} />}</h3>
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
        <RiskCard r={data?.risk} onOpen={() => nav("risk")} />
      </div>


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

function Kpi({ label, tag, tagColor, value, color, info, onClick }) {
  return (
    <div className="card" style={{ cursor: "pointer" }} onClick={onClick}>
      <div className="kpi-label">
        <span>{label} <Info text={info} align="left" /></span> <span className={`tag ${tagColor}`}>{tag}</span>
      </div>
      <div className="kpi-value">{value}</div>
      <Stripe value={1} color={color} />
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
function RiskCard({ r, onOpen }) {
  const pd = r?.past_due_disbursed_musd || 0, wl = r?.watchlist_disbursed_musd || 0;
  return (
    <div className="copilot risk-card" onClick={onOpen} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <div>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Tag>Credit risk at a glance</Tag>
          <span className="small" style={{ opacity: 0.85 }}>Open ↗</span>
        </div>
        <div className="risk-label">Expected credit loss</div>
        <div className="risk-value">{r ? musd(r.expected_credit_loss_musd) : "…"}</div>
      </div>
      <div>
        <div className="risk-split">
          <div style={{ flex: pd || 1 }} className="pd" />
          <div style={{ flex: wl || 1 }} className="wl" />
        </div>
        <div className="risk-legend">
          <span><i className="pd" />Past Due {musd(pd)} · 60% loss</span>
          <span><i className="wl" />Watchlist {musd(wl)}</span>
        </div>
        <div className="risk-foot">{r ? `${int(r.projects)} Category A projects · ${int(r.clients)} clients` : ""}</div>
      </div>
    </div>
  );
}
