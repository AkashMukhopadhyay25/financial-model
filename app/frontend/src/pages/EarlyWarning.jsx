import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { flagReview, invalidate } from "../api.js";
import { AskBar, GenieThread, useGenie } from "../Genie.jsx";
import { date, int, musd } from "../format.js";
import { ErrorBox, EvidenceDrawer, Loading, Tag, useApi } from "../ui.jsx";

const PRIORITY = { HIGH: { label: "High priority", color: "red" }, MEDIUM: { label: "Medium priority", color: "amber" }, REVIEW: { label: "Review", color: "teal" } };
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
                <DotPyramid color="#2f66f6" />
              </div>
              <div className="kpi-foot">{counts.HIGH} high · {counts.MEDIUM} medium · {counts.REVIEW} review</div>
            </div>
            <div className="card">
              <div className="kpi-label">Projects to review</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div className="kpi-value" style={{ color: "#a86a00" }}>{int(data.projects_to_review)}</div>
                <DotPyramid color="#e29a12" />
              </div>
              <div className="kpi-foot">Active projects of flagged clients that are Watchlist, Past Due, rated 5-6 or overdue for review</div>
            </div>
            <div className="copilot" style={{ cursor: "default", minHeight: 0 }}>
              <div>
                <Tag>Guardrail</Tag>
                <h2 style={{ fontSize: 22, margin: "14px 0 8px" }}>These are risk signals, not proof of future default.</h2>
                <p>The agent explains concerns and recommends human investigation.</p>
              </div>
            </div>
          </div>

          <div className="grid g-main mt">
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
                <div className="section-title" style={{ margin: "0 0 10px" }}>Emerging risk alerts</div>
                <span className="small muted">
                  Grouped by review priority using transparent rules ·{" "}
                  <label><input type="checkbox" checked={showReviewed} onChange={(e) => setShowReviewed(e.target.checked)} /> show reviewed</label>
                </span>
              </div>
              {alerts.slice(0, limit).map((a) => (
                <div key={a.client_id} className={`ew-card ${a.reviewed_at ? "reviewed" : ""}`}>
                  <div className="row1">
                    <div className="name">
                      {a.client_name} <Tag color={PRIORITY[a.priority].color} caps>{PRIORITY[a.priority].label}</Tag>
                    </div>
                    <div className="actions">
                      <button className="btn small" onClick={() => markReviewed(a)} disabled={!!a.reviewed_at}>
                        {a.reviewed_at ? `Reviewed ${date(a.reviewed_at)}` : "Mark reviewed"}
                      </button>
                      <button className="btn small" onClick={() => nav("risk", { client: a.client_id })}>WS2 project details</button>
                      <button className="btn small dark" onClick={() => nav("clients", { step: "profile", client: a.client_id })}>WS3 Client 360°</button>
                    </div>
                  </div>
                  <div className="desc">
                    {describe(a)} · exposure affected {musd(a.exposure_affected_musd)} · {a.primary_industry}, {a.primary_region}
                  </div>
                  <div className="trig">
                    Triggered by
                    {signals.filter((s) => a[s.column]).map((s) => (
                      <Tag key={s.column} color={SIG_COLOR[s.column]}>{s.label}</Tag>
                    ))}
                  </div>
                  <div className="sugg">→ Suggested action: {a.suggested_action.toLowerCase()}</div>
                </div>
              ))}
              {!alerts.length && <div className="card empty">No alerts match the selected indicators.</div>}
              {alerts.length > limit && (
                <button className="btn" style={{ width: "100%" }} onClick={() => setLimit((l) => l + 10)}>
                  Show more ({alerts.length - limit} remaining)
                </button>
              )}
            </div>
            <div className="card" style={{ alignSelf: "start", background: "linear-gradient(180deg,#fff,#fff8ef)" }}>
              <h3>Risk indicators</h3>
              <div className="card-sub">Potential indicators in the supplied data · tick to filter</div>
              <div className="checklist mt">
                {signals.map((s) => (
                  <label key={s.column} className="check" style={{ cursor: "pointer", alignItems: "center" }}>
                    <input type="checkbox" checked={on.has(s.column)} onChange={() => toggle(s.column)} style={{ width: 16, height: 16, accentColor: "#0f1222" }} />
                    <span style={{ flex: 1 }}>{s.label}</span>
                    <span className="small muted">{s.clients}</span>
                  </label>
                ))}
              </div>
              <p className="small muted" style={{ marginBottom: 0 }}>
                Suggested actions are investigation, updated review or escalation — not automatic investment decisions. Thresholds: assumption A22.
              </p>
            </div>
          </div>

          <div className="mt">
            <AskBar
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

function describe(a) {
  const parts = [];
  if (a.n_past_due) parts.push(`${a.n_past_due} Past Due`);
  if (a.n_watchlist) parts.push(`${a.n_watchlist} Watchlist`);
  if (a.n_active_rating_5_6) parts.push(`${a.n_active_rating_5_6} Active rated 5-6`);
  if (a.n_review_overdue_active) parts.push(`${a.n_review_overdue_active} reviews overdue (max ${a.max_days_since_review_active} days)`);
  if (a.sig_country_concentration) parts.push(`${Math.round(a.top_country_exposure_share * 100)}% of exposure in ${a.top_country}`);
  return parts.join(" + ") || "Signal triggered";
}

function DotPyramid({ color }) {
  const cols = [1, 2, 4, 5, 4, 2, 1];
  return (
    <svg width="60" height="44" viewBox="0 0 60 44" aria-hidden>
      {cols.map((n, i) =>
        Array.from({ length: n }, (_, j) => (
          <circle key={`${i}-${j}`} cx={6 + i * 8} cy={40 - j * 8} r="3" fill={color} opacity={i === 3 ? 1 : 0.35} />
        )),
      )}
    </svg>
  );
}
