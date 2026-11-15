import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { flagReview, invalidate } from "../api.js";
import { AskBar, GenieThread, useGenie } from "../Genie.jsx";
import { date, int, musd } from "../format.js";
import { ErrorBox, EvidenceDrawer, Info, Loading, SplitBar, Stats, Tag, useApi } from "../ui.jsx";

const PRIORITY = { HIGH: { label: "High priority", color: "red", dot: "red" }, MEDIUM: { label: "Medium priority", color: "amber", dot: "amber" }, REVIEW: { label: "Review", color: "blue", dot: "blue" } };
const SIG_COLOR = {
  sig_multiple_watchlist: "amber", sig_high_risk_rating: "red", sig_review_overdue: "blue",
  sig_existing_past_due: "red", sig_country_concentration: "teal",
};

export default function EarlyWarning() {
  const { nav, openAssumptions, openLibrary, toast } = useApp();
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useApi("/api/early-warning", [tick]);
  const [active, setActive] = useState(null); // null = all signals
  const [showReviewed, setShowReviewed] = useState(false);
  const [limit, setLimit] = useState(8);
  const [evidence, setEvidence] = useState(false);
  const genie = useGenie();

  const signals = data?.signals || [];
  const on = active || new Set(signals.map((s) => s.column));
  const alerts = (data?.alerts || []).filter((a) => signals.some((s) => on.has(s.column) && a[s.column])).filter((a) => showReviewed || !a.reviewed_at);
  const toggle = (col) => {
    const next = new Set(on);
    if (next.has(col)) next.delete(col);
    else next.add(col);
    setActive(next);
  };
  const markReviewed = (a) =>
    flagReview({ entity_type: "client", entity_id: a.client_id, entity_name: a.client_name, action: "mark_reviewed", source_page: "early-warning" })
      .then(() => {
        invalidate("/api/early-warning");
        setTick((t) => t + 1);
        toast(`${a.client_name} marked as reviewed`);
      })
      .catch((e) => toast(`Could not save: ${e.message}`));

  const counts = { HIGH: 0, MEDIUM: 0, REVIEW: 0 };
  (data?.alerts || []).forEach((a) => (counts[a.priority] += 1));
  return (
    <>
      <div className="eyebrow amber">Proposed agent</div>
      <div className="page-head">
        <div>
          <h1 className="title">Early warning centre</h1>
          <div className="subtitle">Emerging risk signals for analyst investigation</div>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => openAssumptions(["A18", "A22"])}>Assumptions</button>
          <button className="btn" onClick={() => setEvidence(true)} disabled={!data}>Evidence / SQL</button>
          <button className="btn dark" onClick={() => nav("briefing")}>Export / briefing</button>
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      {loading && !data && <Loading />}
      {data && (
        <>
          <div className="grid g3">
            <div className="card">
              <div className="kpi-label">Clients flagged</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="kpi-value">{int(data.alerts.length)}</div>
              </div>
              <SplitBar legend segments={[{ label: "High", value: counts.HIGH, color: "#c9302c" }, { label: "Medium", value: counts.MEDIUM, color: "#e29a12" }, { label: "Review", value: counts.REVIEW, color: "#2f66f6" }]} />
            </div>
            <div className="card">
              <div className="kpi-label"><span>Projects to review <Info align="left" text="Active projects of flagged clients that are Watchlist, Past Due, rated 5-6 or overdue for review." /></span></div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="kpi-value" style={{ color: "#a86a00" }}>{int(data.projects_to_review)}</div>
              </div>
              <SplitBar legend segments={[{ label: "To review", value: data.projects_to_review, color: "#e29a12" }, { label: "Other Active", value: Math.max(0, data.active_projects - data.projects_to_review), color: "#c5cad6" }]} />
            </div>
            <div className="copilot" style={{ cursor: "default", minHeight: 0 }}>
              <div>
                <Tag>Guardrail</Tag>
                <h2 style={{ fontSize: 22, margin: "14px 0 8px" }}>These are risk signals, not proof of future default.</h2>
              </div>
            </div>
          </div>

          <div className="grid g-main mt">
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                <div className="section-title" style={{ margin: "0 0 10px" }}>Emerging risk alerts</div>
                <span className="small muted">
                  <label><input type="checkbox" checked={showReviewed} onChange={(e) => setShowReviewed(e.target.checked)} /> show reviewed</label>
                </span>
              </div>
              {alerts.slice(0, limit).map((a, i, arr) => (
                <React.Fragment key={a.client_id}>
                  {(i === 0 || arr[i - 1].priority !== a.priority) && (
                    <div className="ew-group">
                      <span className={`dot ${PRIORITY[a.priority].dot}`} /> {PRIORITY[a.priority].label}
                      <span className="muted">· {int(counts[a.priority])} clients</span>
                      <span className="ew-action">→ {a.suggested_action}</span>
                    </div>
                  )}
                  <div className={`ew-card2 pr-${a.priority.toLowerCase()} ${a.reviewed_at ? "reviewed" : ""}`}>
                    <div className="ew-main">
                      <div className="ew-name">
                        {a.client_name}
                        <span className="ew-meta">{a.primary_industry} · {a.primary_region}</span>
                      </div>
                      <Stats items={[
                        { label: "exposure", value: musd(a.exposure_affected_musd) },
                        { label: "Past Due", value: a.n_past_due, color: "red" },
                        { label: "Watchlist", value: a.n_watchlist, color: "amber" },
                        { label: "rated 5-6", value: a.n_active_rating_5_6, color: "red" },
                        { label: "reviews overdue", value: a.n_review_overdue_active, color: "blue" },
                        a.sig_country_concentration ? { label: `in ${a.top_country}`, value: `${Math.round(a.top_country_exposure_share * 100)}%` } : null,
                      ]} />
                    </div>
                    <div className="ew-side">
                      <button className={`icon-btn ew-check ${a.reviewed_at ? "done" : ""}`} disabled={!!a.reviewed_at}
                              title={a.reviewed_at ? `Reviewed ${date(a.reviewed_at)}` : "Mark reviewed"} aria-label="Mark reviewed" onClick={() => markReviewed(a)}>
                        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M2.5 7.3l2.8 2.8L11.5 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </button>
                      <button className="link small" onClick={() => nav("risk", { client: a.client_id })}>Projects</button>
                      <button className="row-go" aria-label={`Open Client 360° for ${a.client_name}`} title={`Open Client 360° for ${a.client_name}`}
                              onClick={() => nav("clients", { step: "profile", client: a.client_id })}>
                        <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M3 7h8M7.5 3.5L11 7l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
                      </button>
                    </div>
                  </div>
                </React.Fragment>
              ))}
              {!alerts.length && <div className="card empty">No alerts match the selected indicators.</div>}
              {alerts.length > limit && (
                <button className="btn" style={{ width: "100%" }} onClick={() => setLimit((l) => l + 10)}>
                  Show more ({alerts.length - limit} remaining)
                </button>
              )}
            </div>
            <div className="card" style={{ alignSelf: "start" }}>
              <h3>Risk indicators <Info align="left" text="Tick to filter the alerts. Suggested actions are investigation, updated review or escalation, never automatic investment decisions. Thresholds: assumption A22." /></h3>
              <div className="checklist mt">
                {signals.map((s) => (
                  <label key={s.column} className="check" style={{ cursor: "pointer", alignItems: "center" }}>
                    <input type="checkbox" checked={on.has(s.column)} onChange={() => toggle(s.column)} style={{ width: 16, height: 16, accentColor: "#0f1222" }} />
                    <span style={{ flex: 1 }}>{s.label}</span>
                    <span className="small muted">{s.clients}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>

          <div className="mt">
            <AskBar
              variant="hero"
              prompt="Ask the agent"
              placeholder="Which clients show the strongest combination of risk indicators?"
              busy={genie.busy}
              onAsk={genie.ask}
              extraChip={
                <>
                  <button className="chip" onClick={() => genie.ask("Which high-risk Active projects are overdue for review?")}>/risk indicators</button>
                  <button className="chip" onClick={() => genie.ask("Which clients have more than one Watchlist project and what is their disbursed exposure?")}>/multiple watchlist</button>
                </>
              }
            />
            <GenieThread genie={genie} onOpenCertified={openLibrary} />
          </div>
        </>
      )}
      {evidence && data && <EvidenceDrawer items={data.evidence} note="certified_early_warning is built by 01_data/07_client_views from certified_client_scorecard (rules in A22)." onClose={() => setEvidence(false)} />}
    </>
  );
}


