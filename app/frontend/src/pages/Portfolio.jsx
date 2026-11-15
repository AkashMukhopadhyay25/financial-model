import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useApp } from "../App.jsx";
import { get } from "../api.js";
import { AskBar, GenieThread, HistoryDrawer, useGenie } from "../Genie.jsx";
import { date, int, musd } from "../format.js";
import { BarChart, Check, DataTable, DqTag, ErrorBox, EvidenceDrawer, Info, Loading, MiniBars, SqlBlock, StatusTag, Tag, useApi, YearColumns } from "../ui.jsx";

const FILTERS = [
  ["region", "Region"], ["country", "Country"], ["industry", "Industry"], ["department", "Department"],
  ["product_line", "Product line"], ["status", "Status"], ["year", "Year"],
];

export default function Portfolio({ params }) {
  const { openLibrary, openAssumptions } = useApp();
  const genie = useGenie();
  const [filters, setFilters] = useState({});
  const [lib, setLib] = useState([]);
  const [evidence, setEvidence] = useState(false);
  const [genieSql, setGenieSql] = useState(null);
  const [history, setHistory] = useState(false);
  const options = useApi("/api/portfolio/options");
  const qs = useMemo(() => new URLSearchParams(Object.entries(filters).filter(([, v]) => v)).toString(), [filters]);
  const { data, error, loading } = useApi(`/api/portfolio${qs ? `?${qs}` : ""}`);

  useEffect(() => {
    get("/api/answers").then(setLib).catch(() => {});
  }, []);
  // A question handed over from another page (?q=...) is asked once.
  useEffect(() => {
    if (params.q) genie.ask(params.q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params.q, params.t]);

  const suggestions = lib.filter((q) => ["Q01", "Q18", "Q04"].includes(q.question_id))
    .map((q) => ({ label: q.question.length > 34 ? q.question.slice(0, 32) + " …" : q.question, question: q.question }));
  const onSql = useCallback((s) => setGenieSql(s), []);

  const k = data?.kpis;
  const trend = data?.trend || [];
  const activeFilters = Object.entries(filters).filter(([, v]) => v);
  return (
    <>
      <div className="eyebrow blue">WS1 · Genie analytics</div>
      <div className="page-head">
        <div>
          <h1 className="title">Portfolio analytics</h1>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => setEvidence(true)}>Evidence / SQL</button>
          <button className="btn" onClick={() => openAssumptions(data?.assumption_ids)}>Assumptions</button>
          <button className="btn dark" onClick={() => (window.location.hash = "/briefing")}>Export / briefing</button>
          <button className="btn" onClick={() => setHistory(true)}>History</button>
        </div>
      </div>

      <AskBar
        placeholder="Ask about IFC's portfolio…"
        busy={genie.busy}
        onAsk={genie.ask}
        variant="hero"
        chips={suggestions}
        extraChip={<button className="chip plain" onClick={() => openLibrary()}>Browse 30-question library</button>}
      />
      <GenieThread genie={genie} onOpenCertified={openLibrary} onSql={onSql} />
      {history && <HistoryDrawer onClose={() => setHistory(false)} onOpen={genie.show} />}
      {data && (
        <ExplainPanel
          genieSql={genieSql}
          genieTrust={genie.turns.length ? genie.turns[genie.turns.length - 1].result?.trust : null}
          dashboardSql={data.evidence.by_region}
          dq={data.data_quality}
          filters={activeFilters}
        />
      )}
      <div style={{ height: 14 }} />


      <div className="filters">
        <span className="lbl">
          <svg width="12" height="12" viewBox="0 0 12 12"><path d="M1 2h10M3 6h6M5 10h2" stroke="currentColor" strokeWidth="1.4" /></svg> Filters
        </span>
        {FILTERS.map(([key, label]) => (
          <select key={key} className={filters[key] ? "set" : ""} value={filters[key] || ""} aria-label={label}
                  onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value }))}>
            <option value="">{label}</option>
            {(options.data?.[key] || []).map((v) => (
              <option key={v} value={v}>{v}</option>
            ))}
          </select>
        ))}
        {activeFilters.length > 0 && <button className="link" onClick={() => setFilters({})}>Clear</button>}
      </div>

      {error && <ErrorBox error={error} />}
      {loading && !data && <Loading />}
      {k && (
        <div className="grid g3">
          <KpiCard label="Approved investment" value={musd(k.approved_musd, { digits: 1 })} data={trend.slice(-8)} yKey="approved_musd" format={(v) => musd(v)} color="#2f66f6" />
          <KpiCard label="Projects" value={int(k.projects)} data={trend.slice(-8)} yKey="projects" color="#1f9d55" />
          <KpiCard label="Active projects" value={int(k.active_projects)} sub={`${int(k.clients)} clients`} data={trend.slice(-8)} yKey="active_projects" color="#e0457b" />
        </div>
      )}

      {data && (
        <div className="grid g2 mt">
          <div className="card">
            <div className="card-head">
              <h3>Investment by region</h3>
              <Tag>Board-approved</Tag>
            </div>
            <BarChart data={data.by_region} labelKey="region" valueKey="approved_musd" />
          </div>
          <div className="card">
            <div className="card-head">
              <h3>Approved investment trend <Info align="left" text="Board-approved amount by approval year. Hover a column for its value. The hatched last column is a partial year: it runs only to the reporting date." /></h3>
              <Tag>By approval year</Tag>
            </div>
            <YearColumns data={trend} xKey="year" yKey="approved_musd" format={(v) => musd(v, { digits: v >= 1000 && v % 1000 === 0 ? 0 : 1 })}
                         partialYear={k?.reporting_date && !String(k.reporting_date).slice(5).startsWith("12-31") ? String(k.reporting_date).slice(0, 4) : null}
                         partialLabel={k?.reporting_date ? `to ${date(k.reporting_date).replace(/ \d{4}$/, "")}` : ""} />
          </div>
        </div>
      )}

      {data && (
        <div className="mt">
          <div className="card">
            <div className="card-head">
              <h3>Top 25 projects</h3>
              <Tag color="blue">By board-approved amount</Tag>
            </div>
            <DataTable
              rows={data.projects}
              pageSize={10}
              columns={[
                { key: "project_name", label: "Project", strong: true },
                { key: "region", label: "Region" },
                { key: "country", label: "Country" },
                { key: "product_line", label: "Product line" },
                { key: "status", label: "Status", render: (v) => <StatusTag value={v} /> },
                { key: "needs_review", label: "Data quality", render: (v, r) => <DqTag needs={v} severity={r.dq_max_severity} ids={r.dq_flag_ids} messages={r.dq_messages} /> },
                { key: "approved_musd", label: "Approved", num: true, render: (v) => musd(v) },
              ]}
            />
          </div>
        </div>
      )}
      {evidence && data && (
        <EvidenceDrawer items={{ ...(genieSql ? { genie_last_question: genieSql } : {}), ...data.evidence }} onClose={() => setEvidence(false)}
                        note="Every figure on this page comes from certified_investment_portfolio with exactly this SQL." />
      )}
    </>
  );
}

function KpiCard({ label, value, data, yKey, color, sub, format }) {
  return (
    <div className="card">
      <div className="kpi-label">
        <span>{label} <Info align="left" text="Bars: by approval year, last 8 years (the latest year runs to the reporting date). Hover a bar for its value." /></span>
        {sub && <span className="small muted">{sub}</span>}
      </div>
      <div className="kpi-value">{value}</div>
      <MiniBars data={data} xKey="year" yKey={yKey} color={color} format={format} />
    </div>
  );
}

// Collapsible "Answer explanation + SQL evidence": explains Genie's last answer, or the dashboard view before any question.
function ExplainPanel({ genieSql, genieTrust, dashboardSql, dq, filters }) {
  const [open, setOpen] = useState(false);
  const c = genieSql && genieTrust?.counts ? genieTrust.counts : genieSql ? null : dq;
  const dqText = c
    ? `${int(c.rows_needing_review)} of ${int(c.rows_in_scope)} projects in scope carry open flags (${int(c.rows_high_severity)} high); included, not excluded.`
    : (genieTrust?.reasons || ["Data-quality count not available for this query."])[0];
  const summary = `${genieSql ? "Genie's last answer" : "Dashboard view"}${c ? ` · ${int(c.rows_needing_review)} of ${int(c.rows_in_scope)} flagged` : ""}`;
  return (
    <div className={`card explain mt ${open ? "open" : ""}`}>
      <button className="explain-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <h3>Answer explanation + SQL evidence</h3>
        <span className="small muted">{summary}</span>
        <svg className="chev" width="14" height="14" viewBox="0 0 14 14" aria-hidden><path d="M3.5 5.5L7 9l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></svg>
      </button>
      {open && (
        <div className="explain-body">
          <div className="checklist">
            <Check ok detail="Approved = Board total (A08); projects counted by project URL (A01).">Metric definitions</Check>
            <Check ok={!!genieSql || filters.length > 0}
                   detail={genieSql ? "Filters are those in Genie's SQL (WHERE clause)." : filters.length ? filters.map(([k, v]) => `${k} = ${v}`).join(", ") : "No filter: every status included, Dropped too (A03)."}>
              Filters applied
            </Check>
            <Check ok={!!c && c.rows_high_severity === 0} warn={!c || c.rows_high_severity > 0} detail={dqText}>Data-quality caveat</Check>
            <Check ok detail={genieSql ? "The SQL Genie wrote for your last question." : "The SQL behind the region chart on this page."}>Query / intermediate steps</Check>
          </div>
          <SqlBlock sql={genieSql || dashboardSql} comment={genieSql ? "Generated by Genie" : "Investment by region (certified table)"} />
        </div>
      )}
    </div>
  );
}
