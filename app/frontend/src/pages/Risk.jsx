import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { int, musd, musdFull } from "../format.js";
import { Check, DataTable, Dots, DqTag, ErrorBox, EvidenceDrawer, Info, Loading, SplitBar, Stats, Stripe, Tag, useApi } from "../ui.jsx";

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
      <div className="grid g3">
        <div className="card">
          <div className="kpi-label">
            <span>Category A in distress <Info align="left" text="Environmental Category A projects whose latest monitoring status is Past Due or Watchlist (all Active)." /></span>
            <Tag color="red">Category A</Tag>
          </div>
          <div className="kpi-value">{int(tot.projects)}</div>
          <SplitBar segments={[{ label: "Past Due", value: pd.projects, color: "#c9302c" }, { label: "Watchlist", value: wl.projects, color: "#e29a12" }]} />
          <div className="mt">
            <Stats items={[{ label: "Past Due", value: int(pd.projects), color: "red" }, { label: "Watchlist", value: int(wl.projects), color: "amber" }, { label: "clients", value: int(tot.clients) }]} />
          </div>
        </div>
        <div className="card">
          <div className="kpi-label">Disbursed exposure <Tag color="blue">Past Due + Watchlist</Tag></div>
          <div className="kpi-value">{musd(tot.disbursed_capital_tied_up_musd)}</div>
          <SplitBar format={(v) => musd(v)} segments={[{ label: "Past Due", value: pdD, color: "#c9302c" }, { label: "Watchlist", value: wlD, color: "#e29a12" }]} legend />
        </div>
        <div className="copilot" style={{ minHeight: 0, cursor: "default" }}>
          <div>
            <div style={{ fontSize: 13, opacity: 0.9 }}>Expected credit loss</div>
            <h2 style={{ margin: "8px 0 6px", fontSize: 38 }}>{musd(tot.expected_credit_loss_musd)}</h2>
            <p>{Math.round(data.ecl_loss_rate * 100)}% of Past Due disbursed</p>
          </div>
        </div>
      </div>

      <ExposureBreakdown
        pd={pdD} wl={wlD} ecl={tot.expected_credit_loss_musd || 0} undisbursed={tot.undisbursed_commitment_musd || 0}
        approved={tot.approved_musd || 0} rate={data.ecl_loss_rate}
      />

      <div className="mt">
        <div className="card">
          <div className="card-head" style={{ flexWrap: "wrap" }}>
            <h3><span className="dot" style={{ marginRight: 8 }} />Projects requiring attention <Info align="left" text={`${int(tot.projects)} projects across ${int(tot.clients)} clients, all Active, Category A. Approved ${musdFull(tot.approved_musd)}; disbursed ${musdFull(tot.disbursed_capital_tied_up_musd)}; ECL ${musdFull(tot.expected_credit_loss_musd)}.`} /></h3>
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
              { key: "performance_status", label: "Status", render: (v) => <Tag color={v === "Past Due" ? "red" : "amber"}>{v}</Tag> },
              { key: "internal_risk_rating", label: "Rating", num: true },
              { key: "approved_musd", label: "Approved", num: true, render: (v) => musd(v) },
              { key: "disbursed_musd", label: "Disbursed", num: true, render: (v) => musd(v) },
              { key: "needs_review", label: "Data quality", render: (v, r) => <DqTag needs={v} severity={r.dq_max_severity} ids={r.dq_flag_ids} messages={r.dq_messages} /> },
              { key: "client_id", label: "", render: (v, r) => (
                <button className="row-go" aria-label={`Open Client 360° for ${r.client_name}`} title={`Open Client 360° for ${r.client_name}`}
                        onClick={() => nav("clients", { step: "profile", client: v })}>
                  <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M3 7h8M7.5 3.5L11 7l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                </button>
              ) },
            ]}
          />
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
          <li><b>Measures.</b> Approved = board-approved total. Disbursed = monitoring disbursed amount. Undisbursed commitment = approved − disbursed on Active projects.</li>
          <li><b>Expected credit loss.</b> Past Due = default; 60% of disbursed is lost (case brief). Watchlist projects carry no provision under this simplified model.</li>
          <li><b>Reconciliation.</b> On the first delivery the totals were recomputed independently from the two source files: 95 projects, $15,473.36M approved, $11,447.52M disbursed, $3,311.72M ECL.</li>
        </ol>
        <button className="btn" onClick={openAssumptions}>Open the assumptions applied</button>
      </div>
    </div>
  );
}

// Exposure breakdown: every block is sized to its amount. Disbursed (expected loss + recoverable Past Due + Watchlist)
// then the approved-but-undisbursed commitment (A10). ECL applies to Past Due only (A11).
function ExposureBreakdown({ pd, wl, ecl, undisbursed, approved, rate }) {
  const recoverable = Math.max(0, pd - ecl);
  const disbursed = pd + wl;
  const blocks = [
    { key: "ecl", label: "Expected loss", value: ecl, tip: `Expected credit loss: ${Math.round(rate * 100)}% of Past Due disbursed (A11)` },
    { key: "rec", label: "Recoverable", value: recoverable, tip: "Past Due disbursed not expected to be lost" },
    { key: "wl", label: "Watchlist · no loss", value: wl, tip: "Watchlist disbursed: no provision under the brief's model" },
  ];
  const Block = ({ b }) => (
    <div className={`xb-block xb-${b.key}`} style={{ flex: b.value || 0.001 }} title={`${b.tip}: ${musd(b.value)}`}>
      <span>{musd(b.value)}</span>
    </div>
  );
  return (
    <div className="card mt xb">
      <div className="card-head">
        <h3>Exposure breakdown <Info align="left" text="Disbursed exposure is not expected credit loss. The loss rate applies to Past Due only; Watchlist carries no provision. Undisbursed commitments are approved amounts IFC may still fund." /></h3>
        <Tag color="amber">ECL ≠ exposure</Tag>
      </div>
      <div className="xb-row">
        <div className="xb-group" style={{ flex: disbursed || 1 }}>
          <div className="xb-bracket"><span>Disbursed</span><b>{musd(disbursed)}</b></div>
          <div className="xb-blocks">{blocks.map((b) => <Block key={b.key} b={b} />)}</div>
          <div className="xb-legend">
            {blocks.map((b) => <span key={b.key} style={{ flex: b.value || 0.001 }}><i className={`xb-${b.key}`} />{b.label}</span>)}
          </div>
        </div>
        <div className="xb-group" style={{ flex: undisbursed || 0.001 }}>
          <div className="xb-bracket dashed"><span>Not yet disbursed</span></div>
          <div className="xb-blocks">
            <div className="xb-block xb-und" style={{ flex: 1 }} title={`Approved but not yet disbursed (A10): ${musd(undisbursed)}`}><span>{musd(undisbursed)}</span></div>
          </div>
          <div className="xb-legend"><span><i className="xb-und" />Undisbursed</span></div>
        </div>
      </div>
      <div className="xb-foot">
        <span className="xb-pill">ECL {musd(ecl)}</span>
        <span className="muted">= {Math.round(rate * 100)}% × {musd(pd)} Past Due</span>
        <span style={{ marginLeft: "auto" }} className="muted">Total approved <b style={{ color: "var(--ink)" }}>{musd(approved)}</b></span>
      </div>
    </div>
  );
}
