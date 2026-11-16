import React, { useState } from "react";
import { flagReview, invalidate } from "../api.js";
import { useApp } from "../App.jsx";
import { date, dateTime, int, musd, musdFull, pct } from "../format.js";
import { DataTable, ErrorBox, Info, Loading, Modal, SplitBar, Tag, Toast, useApi } from "../ui.jsx";
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
    <div className="card mt brief-sec" id={`brief-${n}`}>
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
        <Stat label="Approved investment" value={musd(k.approved_musd, { digits: 1 })} cta="Portfolio analytics" onClick={() => nav("portfolio")}
              info={`Total amount approved by IFC's Board for all 5,000 projects, every status: Active, Pending, Closed and Dropped (A03, A08). Bars show the split by status. Dropped projects were approved but cancelled, so the figure excluding them is shown underneath. As of ${date(k.reporting_date)}.`}
              bar={<SplitBar format={(v) => musd(v)} segments={statuses.map((x) => ({ label: x.st, value: x.approved_musd || 0, color: STATUS_COLOR[x.st] }))} />}
              note={`${int(k.projects)} projects, all statuses · ${musd(k.approved_musd - (statuses.find((x) => x.st === "Dropped")?.approved_musd || 0), { digits: 1 })} excluding Dropped`} />
        <Stat label="Active projects" value={int(k.active_projects)} cta="Project list" onClick={() => nav("portfolio", { status: "Active" })}
              info="Projects under way (status Active): the only projects carrying current credit exposure (A09). The bar shows their share of all projects; clients = distinct clients with monitored projects."
              bar={<SplitBar segments={[{ label: "Active", value: k.active_projects, color: "#1f9d55" }, { label: "Other", value: k.projects - k.active_projects, color: "#d5d9e3" }]} />}
              note={`${int(k.clients)} clients`} />
        <Stat label="Category A in distress" value={int(tot.projects)} cta="Risk & exposure" onClick={() => nav("risk")}
              info="WS2 Board question: Active projects with environmental and social category A (potentially significant impact) whose latest monitoring status is Past Due (payments overdue) or Watchlist (early signs of difficulty)."
              bar={<SplitBar segments={[{ label: "Past Due", value: pd.projects, color: "#c9302c" }, { label: "Watchlist", value: wl.projects, color: "#e29a12" }]} />}
              note={`${int(pd.projects)} Past Due · ${int(wl.projects)} Watchlist`} />
        <Stat label="Category A expected credit loss" value={musd(tot.expected_credit_loss_musd)} dark cta="Stress test" onClick={() => nav("clients", { step: "stress" })}
              info="What IFC should set aside for the Category A projects above: Past Due projects are treated as in default and 60% of their disbursed amount is assumed lost (A11). Watchlist projects carry no provision in this model. The whole-portfolio figure, all categories, is shown underneath."
              note={`${Math.round(rate * 100)}% of ${musd(pdD)} Past Due disbursed · whole portfolio ${musd(d.overview.portfolio_risk?.expected_credit_loss_musd)}`} />
      </div>

      <WorkingPanel d={d} tot={tot} />

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

      <BriefStrengths s={d.strengths} />

      <Section n="3" title="Board questions: Category A risk" sub={`${int(tot.projects)} projects Past Due or on the Watchlist · ${int(tot.clients)} clients · ${musd(tot.approved_musd)} approved`}
               link="Risk & exposure" onLink={() => nav("risk")}>
        <ExposureBreakdown bare pd={pdD} wl={wlD} ecl={tot.expected_credit_loss_musd || 0}
                           undisbursed={tot.undisbursed_commitment_musd || 0} approved={tot.approved_musd || 0} rate={rate} />
        <div className="chips" style={{ marginTop: 12 }}>
          {d.risk.checks.map((c) => <Tag key={c.name} color={c.ok ? "green" : "amber"}>{c.ok ? "✓" : "!"} {c.name}</Tag>)}
        </div>
        {d.risk.context && (
          <div className="small mt" style={{ color: "var(--green)" }}>
            For context: {int(d.risk.context.performing_category_a)} of {int(d.risk.context.active_category_a)} Active Category A projects are performing.
            Expected credit loss on the whole portfolio is {musd(d.overview.portfolio_risk?.expected_credit_loss_musd)}.
          </div>
        )}
      </Section>

      <BriefScenarios a={d.scenario_watchlist} b={d.scenario_rating} nav={nav} />
      <BriefAllocation al={d.allocation} nav={nav} />

      <Section n="6" title="Client recommendations" sub="For Credit Risk Committee review" link="Client intelligence" onLink={() => nav("clients")}>
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

      {d.allocation && !d.allocation.error && (() => {
        const lim = new Set(d.allocation.regions_to_limit);
        const inLim = d.recommendations.filter((r) => lim.has(r.primary_region));
        if (!inLim.length) return null;
        return (
          <div className="card brief-note">
            <b>Read with section 5:</b> {inLim.length === d.recommendations.length ? "all four clients are" : `${inLim.length} of the four clients are`} in{" "}
            {[...new Set(inLim.map((r) => r.primary_region))].join(", ")}, where new exposure should be limited. Continuing to invest in{" "}
            {inLim.filter((r) => r.recommendation === "CONTINUE").map((r) => r.client_name).join(" and ") || "these clients"} is recommended on the
            condition that the region's share of current exposure does not grow; reducing the other two lowers it.
          </div>
        );
      })()}

      <Section n="7" title="Early warning: highest-priority clients" sub="Risk signals for human investigation, not predictions of default" link="Early warning" onLink={() => nav("early-warning")}>
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

      <Section n="8" title="Data quality" sub={`${int(k.projects_needing_review)} projects flagged (${int(k.projects_high_severity)} high) · included in every figure · routed to owners`}>
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

      <ReviewQueue q={d.review_queue} />
    </div>
  );
}

// ---------------------------------------------------------------- headline: what is working and what is not
function WorkingPanel({ d, tot }) {
  const s = d.strengths && !d.strengths.error ? d.strengths : null;
  const al = d.allocation && !d.allocation.error ? d.allocation : null;
  const k = d.overview.kpis;
  const bands = Object.fromEntries((d.overview.client_bands || []).map((b) => [b.band, b.clients]));
  const alerts = d.overview.alerts || {};
  const sw = d.scenario_watchlist && !d.scenario_watchlist.error ? d.scenario_watchlist : null;
  const go = (n) => document.getElementById(`brief-${n}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
  const working = [
    s && [`${pct(s.performing_projects / s.active_projects)} of Active projects are performing`, `${int(s.performing_projects)} of ${int(s.active_projects)}, ${pct(s.performing_exposure_share)} of current exposure`, 2],
    s && [`${pct(s.completed_projects / s.closed_projects)} of closed projects were completed`, `track record: ${int(s.completed_projects)} of ${int(s.closed_projects)} met their obligations`, 2],
    s?.record_fy && [`Record approvals in FY${s.record_fy.approval_fy}`, `${musd(s.record_fy.approved_musd, { digits: 1 })} across ${int(s.record_fy.projects)} projects`, 2],
    al && [`${al.prioritise_industry} is our strongest industry`, `rank ${al.prioritise_industry_rank} on our track record; the market outlook agrees`, 5],
    bands.CONTINUE && [`${int(bands.CONTINUE)} strong client relationships`, "no distress, low risk ratings: candidates to grow with", 6],
  ].filter(Boolean);
  const notWorking = [
    [`${int(tot.projects)} Category A projects in distress`, `${musd(tot.expected_credit_loss_musd)} provision needed (60% of Past Due disbursed)`, 3],
    al && [`Too concentrated in ${al.regions_to_limit.join(", ")}`, `above the ${pct(al.concentration_limit)} limit of current exposure and ranked last of the regions`, 5],
    al && [`${al.caution_industry} is our weakest industry`, `rank ${al.caution_industry_rank}; the market outlook also counsels caution`, 5],
    alerts.HIGH && [`${int(alerts.HIGH)} clients with high-priority risk signals`, `${int(bands.REDUCE_OR_REVIEW || 0)} clients in the reduce-or-review band`, 7],
    sw && [`Downside: +${musd(sw.summary.ecl_increase_musd)} if the Watchlist defaults`, `${int(sw.summary.shocked_projects)} Watchlist projects, ${musd(sw.summary.shocked_exposure_musd)} disbursed`, 4],
    [`${int(k.projects_needing_review)} projects with open data issues`, `${int(k.projects_high_severity)} high severity; included in every figure and routed to owners`, 8],
  ].filter(Boolean);
  const List = ({ items, tone }) => (
    <ul className={`wnw ${tone}`}>
      {items.map(([t, sub, n]) => (
        <li key={t} onClick={() => go(n)} title={`Go to section ${n}`}>
          <span className="wnw-dot" />
          <span><b>{t}</b><small>{sub}</small></span>
          <span className="wnw-go no-print">§{n}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="grid g2 mt">
      <div className="card wnw-card good">
        <div className="eyebrow green" style={{ marginTop: 0 }}>What is working</div>
        <List items={working} tone="good" />
      </div>
      <div className="card wnw-card bad">
        <div className="eyebrow red" style={{ marginTop: 0 }}>What needs attention</div>
        <List items={notWorking} tone="bad" />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 2. what is going well
function BriefStrengths({ s }) {
  if (!s || s.error) return null;
  const rec = s.record_fy;
  const items = [
    [pct(s.performing_projects / s.active_projects), "of Active projects are performing", `${int(s.performing_projects)} of ${int(s.active_projects)}; ${pct(s.performing_exposure_share)} of current exposure`],
    [pct(s.completed_projects / s.closed_projects), "of closed projects were completed", `${int(s.completed_projects)} of ${int(s.closed_projects)} met their obligations`],
    [int(s.climate_projects), "climate-related projects", `${musd(s.climate_approved_musd, { digits: 1 })} approved`],
    [`${(s.renewable_capacity_mw / 1000).toFixed(1)} GW`, "new renewable capacity", `${int(s.renewable_projects)} generation projects`],
    [int(s.msme_projects), "small-business finance projects", `across ${int(s.countries)} countries`],
    rec && [musd(rec.approved_musd, { digits: 1 }), `approved in FY${rec.approval_fy}`, `record year: ${int(rec.projects)} projects`],
  ].filter(Boolean);
  return (
    <Section n="2" title="What is going well" sub="Same certified data and definitions as the risk sections">
      <div className="strength-grid">
        {items.map(([v, l, f]) => (
          <div key={l} className="strength"><div className="sv">{v}</div><div className="sl">{l}</div><div className="sf">{f}</div></div>
        ))}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- 4. downside scenarios (stress engine, no language model)
function BriefScenarios({ a, b, nav }) {
  const ok = [a, b].filter((x) => x && !x.error);
  if (!ok.length) return null;
  return (
    <Section n="4" title="Downside scenarios" sub="What-ifs from the stress-test engine: certified SQL, A11 loss rate, not forecasts"
             link="Ask the stress-test agent" onLink={() => nav("clients", { step: "stress" })}>
      <div className="grid g2">
        {ok.map((x) => (
          <div key={x.name} className="brief-rec">
            <div className="small muted">{x.name}</div>
            <div className="brief-rec-amt" style={{ color: "var(--red)" }}>+{musd(x.summary.ecl_increase_musd)}</div>
            <div className="small">
              Expected credit loss would rise from {musd(x.summary.ecl_baseline_musd)} to {musd(x.summary.ecl_stressed_musd)}:
              {" "}{int(x.summary.shocked_projects)} projects of {int(x.summary.shocked_clients)} clients, {musd(x.summary.shocked_exposure_musd)} disbursed.
            </div>
            <div className="small muted mt">
              Largest contributors: {x.breakdown.slice(0, 3).map((r) => `${r.region || r.client} (+${musd(r.ecl_increase_musd)})`).join(", ")}
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- 5. where new money should go (allocation rule A23 + research A24)
function BriefAllocation({ al, nav }) {
  if (!al || al.error) return null;
  return (
    <Section n="5" title="Where new commitments should go" sub="Our track record (A23) beside cited market research (A24)"
             link="Ask the capital allocation agent" onLink={() => nav("clients", { step: "allocation" })}>
      <div className="grid g4">
        <div className="brief-rec"><div className="small muted">Prioritise</div><div className="brief-rec-name" style={{ color: "var(--green)" }}>{al.prioritise_industry}</div>
          <div className="small">Rank {al.prioritise_industry_rank}; market {al.data_and_market_agree[al.prioritise_industry] ? "agrees" : "differs"}</div>
          <div className="small muted">{al.market_view_prioritise_industry.join("; ")}</div></div>
        <div className="brief-rec"><div className="small muted">Approach with caution</div><div className="brief-rec-name" style={{ color: "#a86a00" }}>{al.caution_industry}</div>
          <div className="small">Rank {al.caution_industry_rank}; market {al.data_and_market_agree[al.caution_industry] ? "agrees" : "differs"}</div>
          <div className="small muted">{al.market_view_caution_industry.join("; ")}</div></div>
        <div className="brief-rec"><div className="small muted">Grow in</div><div className="brief-rec-name">{al.regions_to_grow.join(" · ")}</div>
          <div className="small muted">Best-ranked regions that are not concentrated</div></div>
        <div className="brief-rec"><div className="small muted">Limit new exposure</div><div className="brief-rec-name" style={{ color: "var(--red)" }}>{al.regions_to_limit.join(" · ")}</div>
          <div className="small muted">Above {pct(al.concentration_limit)} of current exposure or last-ranked</div></div>
      </div>
      <div className="small mt">
        Best segments outside the limited regions: {al.best_segments_outside_limited_regions.join("; ")}.
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------- 9. human review queue
function ReviewQueue({ q }) {
  const [items, setItems] = useState(q?.items || []);
  const [closing, setClosing] = useState(null);
  const [note, setNote] = useState("");
  const [toast, setToast] = useState(null);
  if (!q) return null;
  const open = items.filter((i) => !i.is_reviewed);
  const close = async () => {
    const it = closing;
    await flagReview({ entity_type: it.entity_type, entity_id: it.entity_id, entity_name: it.entity_name, action: "mark_reviewed",
                       note: note || "Reviewed", source_page: "briefing" });
    invalidate("/api/briefing");
    setItems((xs) => xs.map((x) => (x === it ? { ...x, is_reviewed: true, reviewed_at: new Date().toISOString(), decision: note || "Reviewed" } : x)));
    setClosing(null); setNote(""); setToast("Marked as reviewed");
  };
  return (
    <Section n="9" title="Human review queue" sub={`${int(open.length)} open · items sent to the Credit Risk Committee from the agents, clients and projects`}>
      {!items.length && <div className="small muted">Nothing has been sent for review yet. Use "Send to Credit Risk Committee" on an agent's answer, or "Flag for review" on a client.</div>}
      {items.length > 0 && (
        <DataTable
          rows={items}
          columns={[
            { key: "is_reviewed", label: "Status", render: (v) => <Tag color={v ? "green" : "amber"}>{v ? "Reviewed" : "Open"}</Tag> },
            { key: "entity_name", label: "Item", strong: true, render: (v, r) => <span title={r.note}>{v || r.entity_id}</span> },
            { key: "source_page", label: "From" },
            { key: "flagged_by", label: "Sent by" },
            { key: "flagged_at", label: "Sent", render: (v) => dateTime(v) },
            { key: "decision", label: "Decision", render: (v, r) => (r.is_reviewed ? <span title={`${r.reviewed_by || ""} · ${dateTime(r.reviewed_at)}`}>{v}</span> :
                <button className="btn small no-print" onClick={() => setClosing(r)}>Mark reviewed</button>) },
          ]}
        />
      )}
      {closing && (
        <Modal title="Mark as reviewed" onClose={() => setClosing(null)}
               actions={<><button className="btn" onClick={() => setClosing(null)}>Cancel</button><button className="btn dark" onClick={close}>Save decision</button></>}>
          <div className="small" style={{ marginBottom: 8 }}><b>{closing.entity_name || closing.entity_id}</b></div>
          <div className="small muted" style={{ marginBottom: 8 }}>{closing.note}</div>
          <textarea rows={3} style={{ width: "100%", borderRadius: 10, border: "1px solid var(--line)", padding: 8 }}
                    placeholder="Decision, e.g. 'Accepted: propose a reserve top-up' or 'Rejected: scenario too severe'"
                    value={note} onChange={(e) => setNote(e.target.value)} />
          <div className="small muted mt">Saved with your name and the time; the original request stays in the history.</div>
        </Modal>
      )}
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
    </Section>
  );
}

const Stat = ({ label, value, note, bar, dark, info, onClick, cta }) => (
  <div className={`${dark ? "copilot" : "card"} stat-card`} style={dark ? { minHeight: 0 } : undefined} onClick={onClick}
       role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onClick && onClick()} title={cta}>
    <div className="kpi-label" style={dark ? { color: "#fff", opacity: 0.9 } : undefined}>
      <span>{label} {info && <Info text={info} align="left" />}</span>
      {cta && <span className="stat-cta no-print">{cta} ↗</span>}
    </div>
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
    `## Portfolio at a glance`,
    `- ${k.projects} projects, ${musdFull(k.approved_musd)} approved by the Board (all statuses); ${k.active_projects} Active; ${k.clients} clients.`, ``,
    ...(d.strengths && !d.strengths.error ? [`## What is going well`,
      `- ${d.strengths.performing_projects} of ${d.strengths.active_projects} Active projects are performing; ${d.strengths.completed_projects} of ${d.strengths.closed_projects} closed projects were completed.`,
      `- ${d.strengths.climate_projects} climate-related projects; ${d.strengths.renewable_projects} new renewable-generation projects (${d.strengths.renewable_capacity_mw} MW); ${d.strengths.msme_projects} small-business finance projects in ${d.strengths.countries} countries.`, ``] : []),
    `## Category A risk (WS2)`,
    `- ${t.projects} Category A projects are Past Due (${by["Past Due"]?.projects}) or on the Watchlist (${by.Watchlist?.projects}), across ${t.clients} clients, ${musdFull(t.approved_musd)} approved.`,
    `- ${musdFull(t.disbursed_capital_tied_up_musd)} disbursed capital tied up; recommended provision for these Category A projects ${musdFull(t.expected_credit_loss_musd)} (60% of Past Due disbursed).`,
    `- For context, expected credit loss on the whole portfolio is ${musdFull(d.overview.portfolio_risk?.expected_credit_loss_musd)} (${d.overview.portfolio_risk?.past_due_projects} Past Due projects, A11).`, ``,
    ...[d.scenario_watchlist, d.scenario_rating].filter((x) => x && !x.error).flatMap((x, i) => [
      ...(i === 0 ? [`## Downside scenarios (stress-test engine, not forecasts)`] : []),
      `- ${x.name}: expected credit loss ${musdFull(x.summary.ecl_baseline_musd)} → ${musdFull(x.summary.ecl_stressed_musd)} (+${musdFull(x.summary.ecl_increase_musd)}).`]), ``,
    ...(d.allocation && !d.allocation.error ? [`## Where new commitments should go (A23, A24)`,
      `- Prioritise ${d.allocation.prioritise_industry} (rank ${d.allocation.prioritise_industry_rank}), growing in ${d.allocation.regions_to_grow.join(", ")}; approach ${d.allocation.caution_industry} with caution; limit new exposure in ${d.allocation.regions_to_limit.join(", ")}.`,
      `- Market view: ${[...d.allocation.market_view_prioritise_industry, ...d.allocation.market_view_caution_industry].join("; ")}.`, ``] : []),
    `## Client recommendations (WS3) — for Credit Risk Committee review`,
    ...d.recommendations.map((r) => `- **${r.recommendation === "CONTINUE" ? "Continue to invest" : "Reduce / review"}: ${r.client_name} (${r.client_id})** — exposure affected ${musdFull(r.exposure_affected_musd)}. ${r.evidence_summary}. ${r.suggested_action}`),
    ``, `## Early warning (highest priority)`,
    ...d.early_warning.map((e) => `- ${e.client_name}: ${e.triggered_by}. ${e.suggested_action}.`),
    ``, `## Data quality`,
    `- ${k.projects_needing_review} projects carry open data-quality flags (${k.projects_high_severity} high); included in every figure.`,
    ...d.review_owners.map((o) => `  - ${o.owner}: ${o.projects}`),
    ``, `## Assumptions`, ...d.assumptions.map((a) => `- ${a.assumption_id} ${a.topic}: ${a.statement}`),
  ];
  return L.join("\n");
}
