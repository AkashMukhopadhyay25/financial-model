import React, { useEffect, useState } from "react";
import { useApp } from "../App.jsx";
import { AskBar } from "../Genie.jsx";
import { ago, date, int, musd } from "../format.js";
import { ErrorBox, EvidenceDrawer, Loading, OkIcon, Stripe, Tag, useApi } from "../ui.jsx";

const STORIES = [
  { page: "portfolio", eyebrow: "WS1 · Portfolio analytics", color: "blue", q: "What does IFC's portfolio look like?", d: "Explore metrics and answer recurring questions in plain language." },
  { page: "risk", eyebrow: "WS2 · Integrated risk & exposure", color: "red", q: "Where is IFC exposed, and what are the potential losses?", d: "Join project and monitoring records to answer the two Board questions." },
  { page: "clients", eyebrow: "WS3 · Client intelligence", color: "green", q: "Which client relationships should IFC prioritize or reconsider?", d: "Support client recommendations and quantify affected exposure." },
  { page: "early-warning", eyebrow: "Early warning intelligence", color: "amber", q: "What could become a problem before it becomes Past Due?", d: "Flag emerging risk signals for human investigation." },
];

const SLIDES = [
  { h: "Ask the CFO Copilot", p: "Ask a portfolio question, investigate an alert or prepare a Board briefing." },
  { h: "Same question, same answer", p: "Every answer is checked against the certified answer and carries its SQL, assumptions and data-quality caveat." },
  { h: "Humans stay in charge", p: "Recommendations and alerts support decisions; flag anything for review and it is logged." },
];

export default function Overview() {
  const { nav, openLibrary } = useApp();
  const { data, error, loading } = useApi("/api/overview");
  const [slide, setSlide] = useState(0);
  const [evidence, setEvidence] = useState(false);
  const [text, setText] = useState("");
  useEffect(() => {
    const t = setInterval(() => setSlide((s) => (s + 1) % SLIDES.length), 6000);
    return () => clearInterval(t);
  }, []);

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

      {error && <ErrorBox error={error} />}
      {loading && <Loading />}
      {k && (
        <div className="grid g3">
          <Kpi label="Approved investment" tag="Portfolio snapshot" tagColor="blue" value={musd(k.approved_musd, { digits: 1 })} color="var(--blue)"
               foot={`Board-approved total, all statuses (A03, A08) · as of ${date(k.reporting_date)}`} onClick={() => setEvidence(true)} />
          <Kpi label="Projects" tag="Portfolio snapshot" tagColor="green" value={int(k.projects)} color="var(--green)"
               foot={`${int(k.active_projects)} Active · counted by project URL (A01)`} onClick={() => nav("portfolio")} />
          <Kpi label="Clients" tag="Portfolio snapshot" tagColor="pink" value={int(k.clients)} color="var(--pink)"
               foot="Distinct clients with monitored projects" onClick={() => nav("clients", { step: "directory" })} />
        </div>
      )}

      <div className="grid g3 mt">
        <div className="card">
          <div className="card-head">
            <h3>Priority risk alerts</h3>
            <button className="icon-btn" aria-label="Open early warning" onClick={() => nav("early-warning")}>↗</button>
          </div>
          <AlertRow label="High priority" n={a.HIGH} max={maxAlert} color="var(--red)" />
          <AlertRow label="Requiring review" n={a.MEDIUM} max={maxAlert} color="var(--amber)" />
          <AlertRow label="Monitoring reminders" n={a.REVIEW} max={maxAlert} color="var(--blue)" />
          {k && (
            <div className="small muted">
              {int(k.projects_needing_review)} projects carry open data-quality flags ({int(k.projects_high_severity)} high); they stay in every total.
            </div>
          )}
        </div>
        <div className="card" style={{ background: "linear-gradient(180deg,#fff,#f6f8fc)" }}>
          <h3>Recent portfolio activity</h3>
          <div className="card-sub" style={{ marginBottom: 12 }}>Data refreshes, completed reviews and briefing updates</div>
          <div className="activity">
            {(data?.activity || []).map((x) => (
              <div key={x.label}>
                <OkIcon />
                <span>
                  {x.label}
                  <small>{date(x.at)} · {ago(x.at)}</small>
                </span>
              </div>
            ))}
            {data && !data.activity?.length && <div className="muted small">No activity logged yet.</div>}
          </div>
        </div>
        <div className="copilot" onClick={() => document.querySelector("#ask input")?.focus()}>
          <div>
            <Tag>✦ CFO Copilot</Tag>
            <h2>{SLIDES[slide].h}</h2>
            <p>{SLIDES[slide].p}</p>
          </div>
          <div className="progress">
            {SLIDES.map((_, i) => (
              <span key={i} className={i === slide ? "on" : ""} onClick={(e) => { e.stopPropagation(); setSlide(i); }} />
            ))}
          </div>
        </div>
      </div>

      <div className="mt" id="ask">
        <AskBar
          value={text}
          onChange={setText}
          placeholder="Ask a portfolio question, investigate an alert or prepare a Board briefing"
          onAsk={route}
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

      <div className="section-title">One connected product story</div>
      <div className="grid g4">
        {STORIES.map((s) => (
          <div key={s.page} className="card story" onClick={() => nav(s.page)}>
            <div className={`eyebrow ${s.color}`}>{s.eyebrow}</div>
            <h4>{s.q}</h4>
            <p>{s.d}</p>
          </div>
        ))}
      </div>
      {evidence && <EvidenceDrawer items={data.evidence} onClose={() => setEvidence(false)} />}
    </>
  );
}

function Kpi({ label, tag, tagColor, value, color, foot, onClick }) {
  return (
    <div className="card" style={{ cursor: "pointer" }} onClick={onClick}>
      <div className="kpi-label">
        {label} <span className={`tag ${tagColor}`}>{tag}</span>
      </div>
      <div className="kpi-value">{value}</div>
      <Stripe value={1} color={color} />
      <div className="kpi-foot mt">{foot}</div>
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
