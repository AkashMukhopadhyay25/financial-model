import React, { useEffect, useState } from "react";
import { useApp } from "../App.jsx";
import { flagReview, get } from "../api.js";
import { int, musd, pct } from "../format.js";
import { Check, DataTable, DqTag, ErrorBox, EvidenceDrawer, Info, Loading, Modal, Stats, StatusTag, Stripe, Tag, useApi } from "../ui.jsx";

const STEPS = [
  ["directory", "Client directory"],
  ["profile", "Client profile"],
  ["compare", "Client comparison"],
  ["board", "Board recommendation"],
];
const BAND = {
  CONTINUE: { label: "Continue investing", color: "green", bar: "var(--green)" },
  MONITOR: { label: "Monitor", color: "blue", bar: "var(--blue)" },
  REDUCE_OR_REVIEW: { label: "Review exposure", color: "amber", bar: "var(--amber)" },
};
const recLabel = (r) => (r === "CONTINUE" ? { label: "Continue investing", color: "green", bar: "var(--green)" } : { label: "Reduce / review", color: "red", bar: "var(--red)" });

export default function Clients({ params }) {
  const { nav } = useApp();
  const step = params.step || "board";
  const [selected, setSelected] = useState(params.client || null);
  const [search, setSearch] = useState("");
  const [compareIds, setCompareIds] = useState(params.compare ? params.compare.split(",") : []);
  const go = (s, extra = {}) => nav("clients", { step: s, client: selected, ...extra });

  return (
    <>
      <div className="eyebrow green">WS3 · Client 360°</div>
      <div className="page-head">
        <div>
          <h1 className="title">Client intelligence</h1>
          <div className="subtitle">Client relationship recommendations</div>
        </div>
        <div className="actions">
          <form className="pill" style={{ padding: "4px 12px" }} onSubmit={(e) => { e.preventDefault(); nav("clients", { step: "directory", search }); }}>
            <svg width="12" height="12" viewBox="0 0 14 14"><circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M9.5 9.5L13 13" stroke="currentColor" strokeWidth="1.5" /></svg>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search client directory" style={{ border: 0, outline: 0, padding: 6, width: 180 }} />
          </form>
          <button className="btn" onClick={() => go("compare")}>Client comparison</button>
          <button className="btn dark" onClick={() => nav("briefing")}>Export / briefing</button>
        </div>
      </div>
      <div className="steps">
        {STEPS.map(([id, label], i) => (
          <button key={id} className={step === id ? "active" : ""} onClick={() => go(id)}>
            <span className="n">{i + 1}</span> {label}
          </button>
        ))}
      </div>
      {step === "board" && <BoardRecommendation selected={selected} onSelect={setSelected} onCompare={(ids) => { setCompareIds(ids); nav("clients", { step: "compare", compare: ids.join(",") }); }} />}
      {step === "directory" && (
        <Directory initial={params.search || ""} compareIds={compareIds} setCompareIds={setCompareIds}
                   onOpen={(id) => { setSelected(id); nav("clients", { step: "profile", client: id }); }}
                   onCompare={() => nav("clients", { step: "compare", compare: compareIds.join(",") })} />
      )}
      {step === "profile" && (selected ? <Profile id={selected} full /> : <div className="card empty">Pick a client in the directory first.</div>)}
      {step === "compare" && <Compare ids={compareIds} onPick={() => go("directory")} />}
    </>
  );
}

// ---------------------------------------------------------------- step 4: Board recommendation (WS3)
function BoardRecommendation({ selected, onSelect, onCompare }) {
  const { data, error, loading } = useApi("/api/clients/recommendations");
  const [evidence, setEvidence] = useState(false);
  const recs = data?.recommendations || [];
  useEffect(() => {
    if (!selected && recs.length) onSelect(recs[0].client_id);
  }, [recs, selected, onSelect]);
  if (error) return <ErrorBox error={error} />;
  if (loading) return <Loading />;
  if (!recs.length) return <div className="card empty">No recommendations yet: run 04_answers/ws3 on Databricks.</div>;
  return (
    <>
      <div className="grid g4">
        {recs.map((r) => {
          const l = recLabel(r.recommendation);
          return (
            <div key={r.client_id} className={`card client-card ${selected === r.client_id ? "sel" : ""}`} onClick={() => onSelect(r.client_id)}>
              <div className="kpi-label" style={{ color: "var(--ink)", fontSize: 16, fontFamily: "var(--display)" }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.client_name}</span>
                <Tag color={l.color} caps>{l.label}</Tag>
              </div>
              <div className="amt">{musd(r.exposure_affected_musd)}</div>
              <Stripe value={1} color={l.bar} />
              <div className="why">
                <Stats items={[
                  { label: "Past Due", value: r.n_past_due, color: "red" },
                  { label: "Watchlist", value: r.n_watchlist, color: "amber" },
                  { label: "Active", value: r.n_active },
                  { label: "health", value: r.health_score != null ? Math.round(r.health_score) : null, color: r.recommendation === "CONTINUE" ? "green" : "" },
                ]} />
              </div>
              <button className="link" onClick={(e) => { e.stopPropagation(); onSelect(r.client_id); }}>Open Client 360°</button>
            </div>
          );
        })}
      </div>
      <div className="grid g-main mt">
        <div>{selected && <Profile id={selected} />}</div>
        <div>
          <div className="card" style={{ background: "linear-gradient(180deg,#fff,#f2faf5)" }}>
            <h3>Evidence + impact</h3>
            <div className="checklist mt">
              <Check ok detail="Exposure, credit risk, performance history per client (certified_client_scorecard).">Risk / performance profile</Check>
              <Check ok detail="Same band rules for every client (A15); ranked by exposure affected.">Consistent comparison criteria</Check>
              <Check ok detail="Exposure affected = current disbursed + undisbursed commitments (A09, A10).">Affected exposure quantified</Check>
            </div>
            <div className="actions mt">
              <button className="btn small" onClick={() => setEvidence(true)}>View SQL</button>
              <button className="btn small" onClick={() => onCompare(recs.map((r) => r.client_id))}>Compare the four</button>
            </div>
          </div>
          <HumanReview clientId={selected} name={recs.find((r) => r.client_id === selected)?.client_name} />
        </div>
      </div>
      {evidence && <EvidenceDrawer items={{ recommendations: data.evidence }} note="Picks: two largest CONTINUE exposures and two largest distressed exposures (WS3 notebook), with a sensitivity check." onClose={() => setEvidence(false)} />}
    </>
  );
}

function HumanReview({ clientId, name }) {
  const { toast } = useApp();
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  return (
    <div className="copilot mt" style={{ cursor: "default", minHeight: 0 }}>
      <div>
        <Tag>Human review</Tag>
        <h2 style={{ fontSize: 22, margin: "14px 0 0" }}>Recommendations support, not replace, decisions.</h2>
      </div>
      {!open ? (
        <button className="btn" onClick={() => setOpen(true)} disabled={!clientId}>Flag for review</button>
      ) : (
        <div className="mt">
          <textarea className="note" style={{ color: "var(--ink)" }} placeholder={`Note for the Credit Risk Committee about ${name || "this client"}`} value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="actions mt">
            <button className="btn small" onClick={() => setOpen(false)}>Cancel</button>
            <button
              className="btn small"
              onClick={() =>
                flagReview({ entity_type: "client", entity_id: clientId, entity_name: name, action: "flag_for_review", note, source_page: "clients" })
                  .then(() => { toast(`${name} flagged for Credit Risk Committee review`); setOpen(false); setNote(""); })
                  .catch((e) => toast(`Could not save: ${e.message}`))
              }
            >
              Submit flag
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- Client 360
function Profile({ id, full }) {
  const { nav } = useApp();
  const { data, error, loading } = useApi(`/api/clients/${encodeURIComponent(id)}`);
  const [evidence, setEvidence] = useState(false);
  if (error) return <ErrorBox error={error} />;
  if (loading || !data) return <div className="card"><Loading /></div>;
  const s = data.scorecard;
  const band = BAND[s.band] || BAND.MONITOR;
  const disb = s.current_disbursed_exposure_musd || 0, und = s.undisbursed_commitment_musd || 0;
  const climate = data.mix.climate.find((x) => x.label === true || x.label === "true");
  return (
    <>
      <div className="card">
        <div className="card-head">
          <div>
            <h3 style={{ fontSize: 22, fontWeight: 500 }}>Client 360° · {s.client_name}</h3>
            <div className="card-sub">{s.client_id} · {s.primary_industry} · {s.primary_region} <Info align="left" text={s.band_evidence} /></div>
          </div>
          <Tag color={band.color} caps>{band.label}</Tag>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13 }}>
          <span>Exposure breakdown</span>
          <b>Approved {musd(s.approved_musd)}</b>
        </div>
        <div className="split-bar">
          <div style={{ flex: disb || 0.01, background: "repeating-linear-gradient(90deg,#2f66f6 0 3px,transparent 3px 6px)" }} />
          <div style={{ flex: und || 0.01, background: "repeating-linear-gradient(90deg,#16a389 0 10px,transparent 10px 13px)" }} />
        </div>
        <div className="legend">
          <span><i style={{ background: "var(--blue)" }} />Disbursed {musd(disb)}</span>
          <span><i style={{ background: "var(--teal)" }} />Undisbursed commitments {musd(und)}</span>
          {s.expected_credit_loss_musd > 0 && <span><i style={{ background: "var(--red)" }} />ECL {musd(s.expected_credit_loss_musd)}</span>}
        </div>
        <div className="mini-grid mt">
          <Mini k="Projects" v={int(s.n_projects)} big />
          <Mini k="Active" v={int(s.n_active)} big />
          <Mini k="Health score" v={Math.round(s.health_score)} big />
          <Mini k="Distressed" v={pct(s.distress_share, 0)} big />
          <Mini k="Max risk rating" v={s.max_risk_rating_active ?? "–"} big />
          <Mini k="Reviews overdue" v={int(s.n_review_overdue_active)} big />
          <Mini k="Countries" v={int(s.n_countries)} big />
          <Mini k="Climate-related" v={climate ? climate.projects : 0} big />
        </div>
        {data.recommendation && (
          <div className="notice" style={{ background: "var(--blue-soft)", borderColor: "#cbd9ff", color: "var(--ink)" }}>
            <span>✦</span><span><b>{data.recommendation.recommendation === "CONTINUE" ? "Continue to invest" : "Reduce / review"}</b> <Info align="left" text={data.recommendation.suggested_action} /></span>
          </div>
        )}
        {data.early_warning && (
          <div className="notice">
            <span>⚠</span>
            <span><b>Early warning · {data.early_warning.priority.toLowerCase()} priority</b> <Info align="left" text={`${data.early_warning.triggered_by}. Suggested: ${data.early_warning.suggested_action}.`} /></span>
          </div>
        )}
        <div className="actions mt">
          <button className="btn small" onClick={() => nav("risk", { client: s.client_id })}>WS2 project details</button>
          <button className="btn small" onClick={() => setEvidence(true)}>View SQL</button>
        </div>
      </div>
      {full && (
        <div className="card mt">
          <div className="card-head"><h3>Projects</h3><span className="small muted">Riskiest first</span></div>
          <DataTable
            rows={data.projects}
            maxRows={150}
            pageSize={12}
            columns={[
              { key: "project_name", label: "Project", strong: true },
              { key: "country", label: "Country" },
              { key: "status", label: "Status", render: (v) => <StatusTag value={v} /> },
              { key: "performance_status", label: "Performance", render: (v) => <StatusTag value={v} /> },
              { key: "internal_risk_rating", label: "Rating", num: true },
              { key: "approved_musd", label: "Approved", num: true, render: (v) => musd(v) },
              { key: "disbursed_musd", label: "Disbursed", num: true, render: (v) => musd(v) },
              { key: "days_since_last_review", label: "Days since review", num: true },
              { key: "needs_review", label: "DQ", render: (v, r) => <span title={r.dq_messages || ""}><DqTag needs={v} severity={r.dq_max_severity} /></span> },
            ]}
          />
        </div>
      )}
      {evidence && <EvidenceDrawer items={{ projects: data.evidence }} onClose={() => setEvidence(false)} />}
    </>
  );
}

const Mini = ({ k, v, big }) => (
  <div className="mini">
    <div className="k">{k}</div>
    <div className={`v ${big ? "big" : ""}`}>{v}</div>
  </div>
);

// ---------------------------------------------------------------- directory
function Directory({ initial, onOpen, compareIds, setCompareIds, onCompare }) {
  const [search, setSearch] = useState(initial);
  const [band, setBand] = useState("");
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  useEffect(() => {
    const t = setTimeout(() => {
      get(`/api/clients?limit=200&search=${encodeURIComponent(search)}&band=${band}`).then(setData).catch(setErr);
    }, 200);
    return () => clearTimeout(t);
  }, [search, band]);
  const toggle = (id) => setCompareIds((c) => (c.includes(id) ? c.filter((x) => x !== id) : [...c, id].slice(-4)));
  return (
    <div className="card">
      <div className="card-head" style={{ flexWrap: "wrap" }}>
        <div>
          <h3>Client directory</h3>
          <div className="card-sub">Tick up to 4 to compare</div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <input className="note" style={{ minHeight: 0, width: 220 }} placeholder="Search name or ID" value={search} onChange={(e) => setSearch(e.target.value)} />
          <div className="toggle">
            {[["", "All"], ["CONTINUE", "Continue"], ["MONITOR", "Monitor"], ["REDUCE_OR_REVIEW", "Review"]].map(([v, l]) => (
              <button key={l} className={band === v ? "active" : ""} onClick={() => setBand(v)}>{l}</button>
            ))}
          </div>
          <button className="btn small dark" disabled={compareIds.length < 2} onClick={onCompare}>Compare ({compareIds.length})</button>
        </div>
      </div>
      {data && (
        <div className="chips" style={{ marginTop: 0, marginBottom: 10 }}>
          {data.bands.map((b) => (
            <Tag key={b.band} color={BAND[b.band]?.color}>{BAND[b.band]?.label}: {b.clients} clients · {musd(b.exposure_affected_musd)}</Tag>
          ))}
        </div>
      )}
      {err && <ErrorBox error={err} />}
      {!data && !err && <Loading />}
      {data && (
        <DataTable
          rows={data.clients}
          pageSize={15}
          onRowClick={(r) => onOpen(r.client_id)}
          columns={[
            { key: "client_id", label: "", render: (v) => <input type="checkbox" checked={compareIds.includes(v)} onClick={(e) => e.stopPropagation()} onChange={() => toggle(v)} aria-label="Compare" /> },
            { key: "client_name", label: "Client", strong: true },
            { key: "primary_industry", label: "Industry" },
            { key: "primary_region", label: "Region" },
            { key: "band", label: "Band", render: (v) => <Tag color={BAND[v]?.color}>{BAND[v]?.label}</Tag> },
            { key: "n_active", label: "Active", num: true },
            { key: "n_past_due", label: "Past Due", num: true },
            { key: "n_watchlist", label: "Watchlist", num: true },
            { key: "health_score", label: "Health", num: true },
            { key: "exposure_affected_musd", label: "Exposure affected", num: true, render: (v) => musd(v) },
          ]}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------- comparison
const COMPARE_ROWS = [
  ["band", "Band", (v) => <Tag color={BAND[v]?.color}>{BAND[v]?.label}</Tag>],
  ["health_score", "Health score (0-100)"],
  ["exposure_affected_musd", "Exposure affected", musd],
  ["current_disbursed_exposure_musd", "Current disbursed exposure", musd],
  ["undisbursed_commitment_musd", "Undisbursed commitments", musd],
  ["expected_credit_loss_musd", "Expected credit loss", musd],
  ["n_active", "Active projects"],
  ["n_past_due", "Past Due projects"],
  ["n_watchlist", "Watchlist projects"],
  ["n_active_rating_5_6", "Active rated 5-6"],
  ["exposure_weighted_risk_rating", "Exposure-weighted rating"],
  ["distress_share", "Distressed share", (v) => pct(v, 1)],
  ["closed_loss_rate", "Closed at a loss", (v) => pct(v, 1)],
  ["n_review_overdue_active", "Reviews overdue"],
  ["top_country", "Top country"],
  ["top_country_exposure_share", "Top-country share", (v) => pct(v, 0)],
  ["n_projects_needing_review", "Projects with DQ flags"],
];

function Compare({ ids, onPick }) {
  const { data, error, loading } = useApi(ids.length ? `/api/clients/compare?ids=${ids.join(",")}` : null);
  if (!ids.length || ids.length < 2)
    return (
      <div className="card empty">
        Choose 2 to 4 clients to compare. <button className="link" onClick={onPick}>Open the directory</button>
      </div>
    );
  if (error) return <ErrorBox error={error} />;
  if (loading || !data) return <Loading />;
  const rows = ids.map((id) => data.find((d) => d.client_id === id)).filter(Boolean);
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>Client comparison</h3>
          <div className="card-sub">Same criteria for every client (A15)</div>
        </div>
        <button className="btn small" onClick={onPick}>Change clients</button>
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead>
            <tr>
              <th>Measure</th>
              {rows.map((r) => <th key={r.client_id} className="num">{r.client_name}</th>)}
            </tr>
          </thead>
          <tbody>
            {COMPARE_ROWS.map(([k, label, f]) => (
              <tr key={k}>
                <td>{label}</td>
                {rows.map((r) => <td key={r.client_id} className="num">{f ? f(r[k]) : r[k] ?? "–"}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
