import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { int, musd, musdFull } from "../format.js";
import { Check, DataTable, Dots, DqTag, ErrorBox, EvidenceDrawer, Loading, Stripe, Tag, useApi } from "../ui.jsx";

export default function Risk({ params }) {
  const { nav, openAssumptions } = useApp();
  const { data, error, loading } = useApi("/api/risk");
  const [tab, setTab] = useState("All");
  const [category, setCategory] = useState("");
  const [evidence, setEvidence] = useState(false);
  const [method, setMethod] = useState(false);

  if (error) return <Head><ErrorBox error={error} /></Head>;
  if (loading || !data) return <Head><Loading /></Head>;
  const by = Object.fromEntries(data.summary.map((r) => [r.status_label, r]));
  const pd = by["Past Due"] || {}, wl = by["Watchlist"] || {}, tot = by.TOTAL || {};
  const pdD = pd.disbursed_capital_tied_up_musd || 0, wlD = wl.disbursed_capital_tied_up_musd || 0;
  const done = data.checks.filter((c) => c.ok).length;
  let projects = data.projects.filter((p) => tab === "All" || p.performance_status === tab);
  if (params.client) projects = projects.filter((p) => p.client_id === params.client);
  if (category) projects = projects.filter((p) => p.industry === category);
  const industries = [...new Set(data.projects.map((p) => p.industry))].sort();

  return (
    <Head
      actions={
        <>
          <button className="btn" onClick={() => setMethod(true)}>Methodology</button>
          <button className="btn" onClick={() => setEvidence(true)}>Evidence / SQL</button>
          <button className="btn dark" onClick={() => nav("briefing")}>Export / briefing</button>
        </>
      }
    >
      <div className="grid g4">
        <div className="card">
          <div className="kpi-label">Past Due <Tag color="red">Category A</Tag></div>
          <div className="kpi-value red">{int(pd.projects)}</div>
          <Dots n={(pd.projects / (tot.projects || 1)) * 12} color="var(--red)" />
        </div>
        <div className="card">
          <div className="kpi-label">Watchlist <Tag color="amber">Category A</Tag></div>
          <div className="kpi-value amber">{int(wl.projects)}</div>
          <Dots n={(wl.projects / (tot.projects || 1)) * 12} color="var(--amber)" />
        </div>
        <div className="card">
          <div className="kpi-label">Disbursed exposure <Tag color="blue">Past Due + Watchlist</Tag></div>
          <div className="kpi-value">{musd(tot.disbursed_capital_tied_up_musd)}</div>
          <Stripe value={1} color="var(--blue)" />
        </div>
        <div className="copilot" style={{ minHeight: 0, cursor: "default" }}>
          <div>
            <div style={{ fontSize: 13, opacity: 0.9 }}>Expected credit loss</div>
            <h2 style={{ margin: "8px 0 6px", fontSize: 38 }}>{musd(tot.expected_credit_loss_musd)}</h2>
            <p>{Math.round(data.ecl_loss_rate * 100)}% applied to Past Due disbursements only (A11)</p>
          </div>
        </div>
      </div>

      <div className="card mt" style={{ background: "linear-gradient(180deg,#fffaf3,#fff)" }}>
        <div className="card-head">
          <h3>Exposure breakdown</h3>
          <span className="small muted">Past Due and Watchlist disbursements, shown separately</span>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <div style={{ flex: pdD || 1 }}>
            <div style={{ fontFamily: "var(--display)", fontSize: 18 }}>≈ {musd(pdD)}</div>
            <div className="split-bar"><div style={{ flex: 1, background: "repeating-linear-gradient(90deg,#c9302c 0 3px,transparent 3px 6px)" }} /></div>
            <div className="legend"><span><i style={{ background: "var(--red)" }} />Past Due disbursed · {Math.round(data.ecl_loss_rate * 100)}% loss applied</span></div>
          </div>
          <div style={{ flex: wlD || 1 }}>
            <div style={{ fontFamily: "var(--display)", fontSize: 18 }}>≈ {musd(wlD)}</div>
            <div className="split-bar"><div style={{ flex: 1, background: "repeating-linear-gradient(90deg,#e29a12 0 9px,transparent 9px 12px)" }} /></div>
            <div className="legend"><span><i style={{ background: "var(--amber)" }} />Watchlist disbursed · no loss applied</span></div>
          </div>
        </div>
        <div className="notice">
          <span>⚠</span>
          <span>
            <b>Important:</b> Disbursed exposure is not the same as expected credit loss. The {Math.round(data.ecl_loss_rate * 100)}% loss assumption applies only to
            Past Due projects, not Watchlist projects. A further {musd(tot.undisbursed_commitment_musd)} is approved but not yet disbursed on these projects (A10).
          </span>
        </div>
      </div>

      <div className="grid g-main mt">
        <div className="card">
          <div className="card-head" style={{ flexWrap: "wrap" }}>
            <h3><span className="dot" style={{ marginRight: 8 }} />Projects requiring attention</h3>
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <div className="toggle">
                {["All", "Past Due", "Watchlist"].map((t) => (
                  <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>{t}</button>
                ))}
              </div>
              <div className="filters" style={{ margin: 0, padding: 0, border: 0 }}>
                <select className={category ? "set" : ""} value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Industry">
                  <option value="">Industry</option>
                  {industries.map((i) => <option key={i}>{i}</option>)}
                </select>
              </div>
            </div>
          </div>
          {params.client && (
            <div className="small" style={{ marginBottom: 8 }}>
              Filtered to client {params.client}. <button className="link" onClick={() => nav("risk")}>Show all</button>
            </div>
          )}
          <DataTable
            rows={projects}
            maxRows={200}
            pageSize={10}
            columns={[
              { key: "project_name", label: "Project", strong: true },
              { key: "client_name", label: "Client" },
              { key: "country", label: "Country" },
              { key: "environmental_category", label: "Category" },
              { key: "performance_status", label: "Status", render: (v) => <Tag color={v === "Past Due" ? "red" : "amber"}>{v}</Tag> },
              { key: "internal_risk_rating", label: "Rating", num: true },
              { key: "approved_musd", label: "Approved", num: true, render: (v) => musd(v) },
              { key: "disbursed_musd", label: "Disbursed", num: true, render: (v) => musd(v) },
              { key: "needs_review", label: "DQ", render: (v, r) => <DqTag needs={v} severity={r.dq_max_severity} /> },
              { key: "client_id", label: "", render: (v) => <button className="link" onClick={() => nav("clients", { step: "profile", client: v })}>Open client</button> },
            ]}
          />
          <div className="small muted mt">
            {int(tot.projects)} projects across {int(tot.clients)} clients, all Active. Approved {musdFull(tot.approved_musd)}; disbursed {musdFull(tot.disbursed_capital_tied_up_musd)}; ECL {musdFull(tot.expected_credit_loss_musd)}.
          </div>
        </div>
        <div className="card" style={{ background: "linear-gradient(180deg,#fff,#f4f7fd)", alignSelf: "start" }}>
          <h3>Methodology / data quality</h3>
          <div className="card-sub">How the Board answers were built</div>
          <div className="progress-line mt">
            <Stripe value={done / data.checks.length} color="var(--green)" /> {done} of {data.checks.length} checked
          </div>
          <div className="checklist mt">
            {data.checks.map((c) => (
              <Check key={c.name} ok={c.ok} warn={!c.ok} detail={c.detail}>{c.name}</Check>
            ))}
          </div>
          <div className="small muted mt">
            {int(data.data_quality.rows_needing_review)} of {int(data.data_quality.rows_in_scope)} projects in scope carry open data-quality flags ({int(data.data_quality.rows_high_severity)} high).
          </div>
          <button className="btn mt" style={{ width: "100%" }} onClick={() => setEvidence(true)}>View SQL / evidence</button>
        </div>
      </div>
      {evidence && (
        <EvidenceDrawer
          items={{ ...data.evidence, ...Object.fromEntries((data.register || []).map((r) => [`answers_register · ${r.question_id}`, r.sql_text])) }}
          note="The page runs the same SQL as the certified WS2 answers in answers_register, on certified_investment_portfolio."
          onClose={() => setEvidence(false)}
        />
      )}
      {method && (
        <MethodNote onClose={() => setMethod(false)} openAssumptions={() => { setMethod(false); openAssumptions(["A01", "A08", "A09", "A10", "A11", "A17"]); }} />
      )}
    </Head>
  );
}

function Head({ children, actions }) {
  return (
    <>
      <div className="eyebrow red">WS2 · Board questions</div>
      <div className="page-head">
        <div>
          <h1 className="title">Integrated risk &amp; exposure</h1>
          <div className="subtitle">Category A projects requiring attention</div>
        </div>
        <div className="actions">{actions}</div>
      </div>
      {children}
    </>
  );
}

function MethodNote({ onClose, openAssumptions }) {
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ width: "min(720px,100%)" }}>
        <div className="modal-head">
          <h2>Methodology</h2>
          <button className="btn small" onClick={onClose}>Close</button>
        </div>
        <ol style={{ lineHeight: 1.6, fontSize: 13.5 }}>
          <li><b>Join.</b> Each project is joined to its monitoring record on <code>project_url</code>. Project Number is not unique (3,559 values for 5,000 projects); joining on it would inflate monitoring rows from 3,768 to 6,477.</li>
          <li><b>Scope.</b> Environmental Category A and the latest performance status Past Due or Watchlist.</li>
          <li><b>Measures.</b> Approved = Board-approved total. Disbursed = monitoring disbursed amount. Undisbursed commitment = approved − disbursed on Active projects.</li>
          <li><b>Expected credit loss.</b> Past Due = default; 60% of disbursed is lost (case brief). Watchlist projects carry no provision under this simplified model.</li>
          <li><b>Reconciliation.</b> On the first delivery the totals were recomputed independently from the two source files: 95 projects, $15,473.36M approved, $11,447.52M disbursed, $3,311.72M ECL.</li>
        </ol>
        <button className="btn" onClick={openAssumptions}>Open the assumptions applied</button>
      </div>
    </div>
  );
}
