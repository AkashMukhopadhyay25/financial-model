import React, { useState } from "react";
import { useApp } from "../App.jsx";
import { flagReview, invalidate, post } from "../api.js";
import { int, musd } from "../format.js";
import { Drawer, ErrorBox, EvidenceDrawer, Info, Loading, Modal, Tag, useApi, YearColumns } from "../ui.jsx";

const DIRECTION = {
  Deteriorated: { color: "red", label: "Deteriorated" },
  Mixed: { color: "amber", label: "Mixed" },
  Improved: { color: "green", label: "Improved" },
  "New business": { color: "blue", label: "New business" },
};
const KPI_TEXT = {
  R01: { label: "Past Due projects", foot: "Projects behind on repayments" },
  R02: { label: "Watchlist projects", foot: "Projects showing early signs of stress" },
  R04: { label: "Expected credit loss", foot: "60% of disbursed on Past Due projects" },
  M01: { label: "Overdue monitoring reviews", foot: "Active projects past their review deadline" },
};
const FILTERS = [
  { id: "attention", label: "Needs attention", dirs: ["Deteriorated", "Mixed"] },
  { id: "improved", label: "Improved", dirs: ["Improved"] },
  { id: "growth", label: "New business", dirs: ["New business"] },
  { id: "all", label: "All changes", dirs: ["Deteriorated", "Mixed", "Improved", "New business"] },
];
const monthName =(m) => (m ? new Date(`${m}-01T00:00:00`).toLocaleString("en-US", { month: "long", year: "numeric" }) : "");
const short = (m) => (m ? new Date(`${m}-01T00:00:00`).toLocaleString("en-US", { month: "short" }) : "");

function fmtKpi(v, unit) {
  if (v === null || v === undefined) return "–";
  return unit === "USD M" ? musd(v) : int(Math.round(v));
}

export default function Monthly({ params }) {
  const { nav } = useApp();
  const [month, setMonth] = useState(params.month || "");
  const [tick, setTick] = useState(0);
  const { data, error, loading } = useApi(`/api/monthly/review?month=${month}`, [tick]);
  const [filter, setFilter] = useState("attention");
  const [shown, setShown] = useState(8);
  const [client, setClient] = useState(null);
  const openClient = (name) => setClient((data?.clients || []).find((c) => c.client_name === name) || { client_name: name });
  const [evidence, setEvidence] = useState(null);
  const [upload, setUpload] = useState(false);

  const head = (
    <div className="page-head">
      <div>
        <h1 className="title">{data?.ready ? `What changed in ${data.month_name}` : "Monthly review"}</h1>
        <div className="subtitle">
          {data?.ready ? (
            <>
              Compared with {data.previous_name}: of {int(data.total_clients)} clients,{" "}
              <b style={{ color: "var(--red)" }}>{int(FILTERS[0].dirs.reduce((n, d) => n + (data.counts[d] || 0), 0))} need attention</b>,{" "}
              <b style={{ color: "var(--green)" }}>{int(data.counts.Improved || 0)} improved</b> and{" "}
              <b style={{ color: "var(--blue)" }}>{int(data.counts["New business"] || 0)} added new business</b>
            </>
          ) : "Month-on-month changes in the certified portfolio"}
        </div>
        <div className="small muted" style={{ marginTop: 4 }}>
          Demo months July–October 2026 (synthetic deliveries). Every other page is as of 30 June 2026.
        </div>
      </div>
      <div className="actions">
        {data?.ready && (
          <select className="btn select-btn" value={data.month} aria-label="Reporting month" onChange={(e) => { setMonth(e.target.value); setShown(8); }}>
            {data.months.slice(1).reverse().map((m) => <option key={m} value={m}>{monthName(m)}</option>)}
          </select>
        )}
        <button className="btn" disabled={!data?.ready} onClick={() => setEvidence(data.evidence)}>Evidence / SQL</button>
        <button className="btn dark" onClick={() => setUpload(true)}>Load a new month</button>
      </div>
    </div>
  );

  if (error) return <>{head}<ErrorBox error={error} /></>;
  if (loading && !data) return <>{head}<Loading /></>;

  const dirs = FILTERS.find((f) => f.id === filter).dirs;
  const clients = (data?.clients || []).filter((c) => dirs.includes(c.direction));
  return (
    <>
      <div className="eyebrow blue">Monthly review</div>
      {head}
      {!data.ready && (
        <div className="card">
          <h3>Not enough history yet</h3>
          <p className="muted">At least two reporting months are needed. Use <b>Load a new month</b> to add one.</p>
        </div>
      )}
      {data.ready && (
        <>
          <div className="grid g4">
            {data.kpis.map((k) => <KpiCard key={k.kpi_id} k={k} prev={`${short(data.previous)} '${String(data.previous || "").slice(2, 4)}`} />)}
          </div>

          <div className="grid g-main mt" style={{ alignItems: "start" }}>
            <div>
              <div className="section-title" style={{ marginTop: 6 }}>Clients that changed in {data.month_name}</div>
              <div className="seg" style={{ marginTop: 0 }}>
                {FILTERS.map((f) => (
                  <button key={f.id} className={filter === f.id ? "active" : ""} onClick={() => { setFilter(f.id); setShown(8); }}>
                    {f.label} · {f.dirs.reduce((s, d) => s + (data.counts[d] || 0), 0)}
                  </button>
                ))}
              </div>
              {clients.slice(0, shown).map((c) => (
                <ClientRow key={c.client_name} c={c} onOpen={() => setClient(c)} />
              ))}
              {clients.length === 0 && <div className="empty">No clients in this group this month.</div>}
              {clients.length > shown && (
                <button className="btn" onClick={() => setShown((n) => n + 10)}>Show {Math.min(10, clients.length - shown)} more clients</button>
              )}
            </div>
            <div style={{ display: "grid", gap: 14, marginTop: 52 }}>
              {data.balance && <MonthBalance b={data.balance} prev={data.previous_name} onFilter={(f) => { setFilter(f); setShown(8); }} />}
              {data.actions && <ActionList actions={data.actions} month={data.month_name} openClient={openClient} />}
              <div className="small muted">
                Every count and amount comes from the certified month-on-month changes (project_month_changes); the same data always gives the same view.
              </div>
            </div>
          </div>

          <PortfolioTrend months={data.months} />
        </>
      )}

      {client && (
        <ClientDrawer c={client} month={data.month} onClose={() => setClient(null)}
                      onProfile={() => client.client_id && nav("clients", { step: "profile", client: client.client_id })}
                      onEvidence={setEvidence} />
      )}
      {evidence && <EvidenceDrawer items={evidence} onClose={() => setEvidence(null)} />}
      {upload && <UploadModal months={data?.months || []} onClose={() => setUpload(false)}
                              onStarted={() => { invalidate("/api/monthly"); setTick((t) => t + 1); }} />}
    </>
  );
}

function KpiCard({ k, prev }) {
  const t = KPI_TEXT[k.kpi_id] || { label: k.kpi_name, foot: "" };
  const color = k.assessment === "Improving" ? "green" : k.assessment === "Deteriorating" ? "red" : "grey";
  const diff = k.change || 0;
  const arrow = diff > 0 ? "↑" : diff < 0 ? "↓" : "";
  const diffTxt = k.unit === "USD M" ? musd(Math.abs(diff)) : int(Math.abs(Math.round(diff)));
  return (
    <div className="card">
      <div className="kpi-label">
        <span>{t.label} <Info text={t.foot} align="left" /></span>
      </div>
      <div className={`kpi-value ${color === "red" ? "red" : ""}`}>{fmtKpi(k.value, k.unit)}</div>
      <Tag color={color} title={`${fmtKpi(k.previous_value, k.unit)} in ${prev}`}>
        {diff === 0 ? `No change from ${prev}` : `${arrow} ${diffTxt} from ${prev}`}
      </Tag>
    </div>
  );
}

// ---------------------------------------------------------------- the month in balance: worse vs better, side by side
function MonthBalance({ b, prev, onFilter }) {
  const g = b.growth;
  const verdict = { improving: ["green", "Credit quality improved"], deteriorating: ["red", "Credit quality deteriorated"], mixed: ["amber", "A mixed month"] }[b.verdict];
  return (
    <div className="card">
      <div className="eyebrow" style={{ marginTop: 0 }}>Balance of the month</div>
      <div className="balance-verdict">
        <Tag color={verdict[0]}>{verdict[1]}</Tag>
        <span className="small muted">{int(b.credit_better)} recoveries and upgrades vs {int(b.credit_worse)} slips and downgrades since {prev}</span>
      </div>
      <div className="balance-head small muted"><span>Worse</span><span /><span>Better</span></div>
      {b.pairs.map((p) => {
        const max = Math.max(1, p.worse.n, p.better.n);
        return (
          <div key={p.id} className="balance-row">
            <div className="balance-label">{p.label}</div>
            <div className="balance-bars">
              <button className="bside worse" disabled={!p.worse_filter} onClick={() => p.worse_filter && onFilter(p.worse_filter)}
                      title={p.worse_filter ? "Show these clients" : undefined}>
                <span className="bnum">{int(p.worse.n)} <small>{p.worse_label}</small>{p.worse.musd > 0 && <em>{musd(p.worse.musd)}</em>}</span>
                <i style={{ width: `${(100 * p.worse.n) / max}%` }} />
              </button>
              <button className="bside better" disabled={!p.better_filter} onClick={() => p.better_filter && onFilter(p.better_filter)}
                      title={p.better_filter ? "Show these clients" : undefined}>
                <i style={{ width: `${(100 * p.better.n) / max}%` }} />
                <span className="bnum">{int(p.better.n)} <small>{p.better_label}</small>{p.better.musd > 0 && <em>{musd(p.better.musd)}</em>}</span>
              </button>
            </div>
          </div>
        );
      })}
      <div className="balance-growth">
        <span className="small muted">New business</span>
        <button className="link" onClick={() => onFilter("growth")}>
          <b>{int(g.BOARD_APPROVED.n)}</b> Board approvals ({musd(g.BOARD_APPROVED.musd)}) · <b>{int(g.SIGNED.n)}</b> signings · <b>{int(g.FIRST_DISBURSEMENT.n)}</b> first disbursements · <b>{int(g.NEW_PROJECT.n)}</b> new projects
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- the month's actions: owner, money at stake, the actual names, one click to act
const PRIORITY = { high: ["red", "High"], medium: ["amber", "Medium"], routine: ["blue", "Routine"] };

function ActionList({ actions, month, openClient }) {
  const { nav } = useApp();
  const [sent, setSent] = useState({});
  const send = async (a) => {
    if (sent[a.id]) return;
    setSent((s) => ({ ...s, [a.id]: "sending" }));
    for (const it of a.items) {
      await flagReview({ entity_type: "client", entity_id: it.client_id || it.name, entity_name: it.name, action: "flag_for_review",
                         note: `${month} · ${a.title}: ${it.detail} (${musd(it.musd)}). Owner: ${a.owner}.`, source_page: "monthly-review" });
    }
    setSent((s) => ({ ...s, [a.id]: "sent" }));
  };
  return (
    <div className="card">
      <div className="eyebrow blue" style={{ marginTop: 0 }}>Actions for {month}</div>
      {actions.map((a, i) => (
        <div key={a.id} className="action">
          <div className="action-top">
            <span className="action-n">{i + 1}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="action-title">{a.title}</div>
              <div className="small muted">{a.why}</div>
            </div>
            <Tag color={PRIORITY[a.priority][0]}>{PRIORITY[a.priority][1]}</Tag>
          </div>
          {a.items.length > 0 && (
            <div className="action-items">
              {a.items.slice(0, 3).map((it, j) => (
                <button key={j} className="action-item" onClick={() => openClient(it.name)} title={it.detail}>
                  <span className="ai-name">{it.name}</span><span className="ai-amt">{musd(it.musd)}</span>
                  <span className="ai-detail">{it.detail}</span>
                </button>
              ))}
              {a.items.length > 3 && <div className="small muted">+{a.items.length - 3} more (all {a.items.length} are sent for review)</div>}
            </div>
          )}
          <div className="action-foot">
            <span className="small muted">Owner: <b>{a.owner}</b></span>
            {a.cta === "send" && (
              <button className="btn small" disabled={!!sent[a.id]} onClick={() => send(a)}>
                {sent[a.id] === "sent" ? "In the review queue ✓" : sent[a.id] ? "Sending…" : `Send ${a.items.length === 1 ? "it" : `all ${a.items.length}`} for review`}
              </button>
            )}
            {a.cta === "early_warning" && <button className="btn small" onClick={() => nav("early-warning")}>Open Early warning</button>}
          </div>
        </div>
      ))}
    </div>
  );
}

function Takeaways({ title, color, items, numbered }) {
  return (
    <div className="card">
      <div className={`eyebrow ${color}`} style={{ marginTop: 0 }}>{title}</div>
      <ol style={{ margin: "8px 0 0", paddingLeft: numbered ? 18 : 0, listStyle: numbered ? "decimal" : "none" }}>
        {items.map((s, i) => (
          <li key={i} style={{ fontSize: 13.5, lineHeight: 1.5, marginBottom: 8, display: numbered ? "list-item" : "flex", gap: 8 }}>
            {!numbered && <span className={`dot ${color}`} style={{ marginTop: 7, flex: "none" }} />}
            <span>{s}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function ClientRow({ c, onOpen }) {
  const d = DIRECTION[c.direction];
  const facts = [
    c.to_past_due && { t: `${c.to_past_due} into Past Due`, cls: "red" },
    c.to_watchlist && { t: `${c.to_watchlist} onto Watchlist`, cls: "amber" },
    c.downgrades && { t: `${c.downgrades} rating downgrade${c.downgrades > 1 ? "s" : ""}`, cls: "amber" },
    c.recoveries && { t: `${c.recoveries} recover${c.recoveries > 1 ? "ies" : "y"}`, cls: "green" },
    c.growth && { t: `${c.growth} new-business step${c.growth > 1 ? "s" : ""}`, cls: "blue" },
  ].filter(Boolean);
  const amount = c.exposure_musd > 0 ? { k: "Disbursed affected", v: c.exposure_musd } : c.approved_musd > 0 ? { k: "Newly approved", v: c.approved_musd } : null;
  return (
    <div className={`ew-card2 dir-${d.color}`} style={{ cursor: "pointer" }} onClick={onOpen}>
      <div className="ew-main">
        <div className="ew-name">{c.client_name} <Tag color={d.color}>{d.label}</Tag></div>
        <div className="mo-headline">{c.headline}</div>
        <div className="stats">
          {facts.map((f) => <span key={f.t} className={`stat ${f.cls}`}>{f.t}</span>)}
        </div>
      </div>
      <div className="ew-side">
        {amount && (
          <div className="mo-amt">
            <span>{amount.k}</span>
            <b>{musd(amount.v)}</b>
          </div>
        )}
        <button className="row-go" aria-label={`Details for ${c.client_name}`} title="View details"
                onClick={(e) => { e.stopPropagation(); onOpen(); }}>
          <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M3 7h8M7.5 3.5L11 7l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /></svg>
        </button>
      </div>
    </div>
  );
}

const AMOUNT_LABEL = {
  PERFORMANCE_WORSENED: "Disbursed on this project", PERFORMANCE_IMPROVED: "Disbursed on this project",
  RISK_DOWNGRADE: "Current exposure", RISK_UPGRADE: "Current exposure", REVIEW_OVERDUE: "Current exposure",
  REVIEW_OVERDUE_CLEARED: "Current exposure", BOARD_APPROVED: "Approved", SIGNED: "Approved", NEW_PROJECT: "Proposed",
  FIRST_DISBURSEMENT: "First disbursement", STATUS_CHANGE: "Approved",
};

const CLIENT_SERIES = [
  { key: "exposure_musd", label: "Disbursed exposure", fmt: musd },
  { key: "at_risk", label: "Projects Past Due or on Watchlist", fmt: int },
  { key: "avg_rating", label: "Average risk rating", fmt: (v) => Number(v).toFixed(2) },
];

function ClientDrawer({ c, month, onClose, onProfile, onEvidence }) {
  const { data, error, loading } = useApi(`/api/monthly/client?name=${encodeURIComponent(c.client_name)}&month=${month}`);
  const [series, setSeries] = useState("at_risk");
  const hist = (data?.history || []).map((h) => ({ ...h, at_risk: h.past_due + h.watchlist, label: short(h.month) }));
  const now = hist.find((h) => h.month === month);
  const before = hist[hist.findIndex((h) => h.month === month) - 1];
  const s = CLIENT_SERIES.find((x) => x.key === series);
  const d = DIRECTION[c.direction];
  const delta = (key, fmt = int) => {
    if (!now || !before) return "";
    const v = (now[key] || 0) - (before[key] || 0);
    return v === 0 ? "no change" : `${v > 0 ? "+" : "−"}${fmt(Math.abs(v))} vs ${short(before.month)}`;
  };
  return (
    <Drawer title={c.client_name} onClose={onClose}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 14 }}>
        <Tag color={d.color}>{d.label} in {monthName(month)}</Tag>
        {c.client_id && <span className="small muted">{c.client_id}</span>}
      </div>
      {error && <ErrorBox error={error} />}
      {loading && <Loading />}
      {now && (
        <>
          <div className="mini-grid">
            <div className="mini"><div className="k">Past Due</div><div className="v big">{int(now.past_due)}</div><div className="k">{delta("past_due")}</div></div>
            <div className="mini"><div className="k">Watchlist</div><div className="v big">{int(now.watchlist)}</div><div className="k">{delta("watchlist")}</div></div>
            <div className="mini"><div className="k">Disbursed exposure</div><div className="v big">{musd(now.exposure_musd)}</div><div className="k">{delta("exposure_musd", musd)}</div></div>
            <div className="mini"><div className="k">Avg risk rating</div><div className="v big">{now.avg_rating ? Number(now.avg_rating).toFixed(1) : "–"}</div><div className="k">{int(now.active)} active projects</div></div>
          </div>

          <div className="card-head mt" style={{ marginBottom: 0 }}>
            <h3 style={{ margin: 0 }}>Month by month</h3>
            <select className="btn small" value={series} onChange={(e) => setSeries(e.target.value)} aria-label="Measure">
              {CLIENT_SERIES.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
            </select>
          </div>
          <YearColumns data={hist} xKey="label" yKey={series} format={s.fmt} height={190} labelFmt={(l) => l} defaultIndex="last" />

          <h3 style={{ margin: "18px 0 8px" }}>What changed in {monthName(month)}</h3>
          <div className="activity">
            {data.events.map((e, i) => (
              <div key={i}>
                <span className={`dot ${e.impact === "Negative" ? "red" : e.impact === "Positive" ? "green" : "blue"}`} style={{ marginTop: 6, flex: "none" }} />
                <span>
                  <b style={{ fontWeight: 600 }}>{e.project_name}</b> · {e.text}
                  {e.amount_musd && AMOUNT_LABEL[e.change_type] ? <small>{AMOUNT_LABEL[e.change_type]}: {musd(e.amount_musd)}</small> : null}
                </span>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
            {c.client_id && <button className="btn dark" onClick={onProfile}>Open client profile</button>}
            <button className="btn" onClick={() => onEvidence(data.evidence)}>Evidence / SQL</button>
          </div>
        </>
      )}
    </Drawer>
  );
}

const TREND = [
  { id: "R01", label: "Past Due" },
  { id: "R02", label: "Watchlist" },
  { id: "R04", label: "Expected credit loss" },
  { id: "M01", label: "Overdue reviews" },
];

function PortfolioTrend({ months }) {
  const { data } = useApi("/api/monthly/series");
  const [kpi, setKpi] = useState("R01");
  const line = (data?.rows || []).filter((r) => r.kpi_id === kpi).map((r) => ({ ...r, label: short(r.month_label) }));
  const unit = line[0]?.unit;
  return (
    <div className="card mt">
      <div className="card-head">
        <h3>Portfolio trend · {monthName(months[0])} to {monthName(months[months.length - 1])}</h3>
        <div className="toggle">
          {TREND.map((t) => (
            <button key={t.id} className={kpi === t.id ? "active" : ""} onClick={() => setKpi(t.id)}>{t.label}</button>
          ))}
        </div>
      </div>
      {line.length > 0 ? (
        <YearColumns data={line} xKey="label" yKey="value" format={(v) => fmtKpi(v, unit)} width={1100} height={240}
                     labelFmt={(l) => l} defaultIndex="last" />
      ) : <Loading />}
    </div>
  );
}

function UploadModal({ months, onClose, onStarted }) {
  const { toast } = useApp();
  const [month, setMonth] = useState("");
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(null);
  const runs = useApi("/api/monthly/runs", [done]);
  const valid = /^20\d\d-(0[1-9]|1[0-2])$/.test(month);

  const submit = async () => {
    setBusy(true);
    try {
      const payload = await Promise.all([...files].map((f) => new Promise((res, rej) => {
        const r = new FileReader();
        r.onload = () => res({ name: f.name, content_base64: String(r.result).split(",")[1] });
        r.onerror = rej;
        r.readAsDataURL(f);
      })));
      const out = await post("/api/monthly/upload", { month, files: payload });
      setDone(out);
      onStarted();
      invalidate("/api/monthly/runs");
    } catch (e) {
      toast(`Upload failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };
  const last = runs.data?.[0];
  return (
    <Modal title="Load a new month" onClose={onClose}
           actions={<button className="btn dark" disabled={busy || !valid || !files.length} onClick={submit}>{busy ? "Uploading…" : "Upload and process"}</button>}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Add the month's projects and monitoring files. They are checked against the data contracts, certified and added to the
        history in about 10–15 minutes. Uploading a month again replaces only that month.
      </p>
      <div style={{ display: "grid", gap: 10 }}>
        <input placeholder="Reporting month, e.g. 2026-11" value={month} onChange={(e) => setMonth(e.target.value.trim())} />
        <input type="file" accept=".csv" multiple onChange={(e) => setFiles(e.target.files || [])} />
      </div>
      {month && !valid && <div className="error mt">Use the format 2026-11.</div>}
      {valid && months.includes(month) && (
        <div className="notice mt"><span>⚠</span><span>{monthName(month)} is already loaded. These files will replace it.</span></div>
      )}
      {done && <div className="notice mt"><span>✓</span><span>Files received. Processing has started; this page updates when it finishes.</span></div>}
      {last && (
        <div className="small muted mt">
          Latest processing run: <Tag color={last.state === "SUCCESS" ? "green" : last.state === "FAILED" ? "red" : "blue"}>{last.state === "SUCCESS" ? "Completed" : last.state === "FAILED" ? "Stopped: check the file" : "In progress"}</Tag>{" "}
          {last.started_ms ? new Date(last.started_ms).toLocaleString() : ""}
        </div>
      )}
      <div className="small muted mt">Months loaded: {months.map(monthName).join(", ") || "none"}</div>
    </Modal>
  );
}
