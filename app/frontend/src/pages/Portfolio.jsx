import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useApp } from "../App.jsx";
import { get } from "../api.js";
import { AskBar, GenieThread, useGenie } from "../Genie.jsx";
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
        </div>
      </div>

      <AskBar
        placeholder="Ask about IFC's portfolio…"
        busy={genie.busy}
        onAsk={genie.ask}
        variant="hero"
        right={<span className="hero-pill">Powered by Genie · governed data</span>}
        chips={suggestions}
        extraChip={<button className="chip plain" onClick={() => openLibrary()}>Browse 30-question library</button>}
      />
      <GenieThread genie={genie} onOpenCertified={openLibrary} onSql={onSql} />
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
        <div className="grid g-main mt">
          <div className="card">
            <div className="card-head">
              <h3>Results table</h3>
              <span className="small muted">Top 25 projects by Board-approved amount</span>
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
                { key: "needs_review", label: "Data quality", render: (v, r) => <DqTag needs={v} severity={r.dq_max_severity} /> },
                { key: "approved_musd", label: "Approved", num: true, render: (v) => musd(v) },
              ]}
            />
          </div>
          <div className="card" style={{ background: "linear-gradient(180deg,#fff,#f4f7fd)" }}>
            <h3>Answer explanation + SQL evidence</h3>
            <div className="checklist mt">
              <Check ok detail="Approved = Board total (A08); projects counted by project URL (A01).">Metric definitions</Check>
              <Check ok={activeFilters.length > 0} detail={activeFilters.length ? activeFilters.map(([k2, v]) => `${k2} = ${v}`).join(", ") : "No filter: every status included, Dropped too (A03)."}>
                Filters applied
              </Check>
              <Check ok={data.data_quality.rows_high_severity === 0} warn={data.data_quality.rows_high_severity > 0}
                     detail={`${int(data.data_quality.rows_needing_review)} of ${int(data.data_quality.rows_in_scope)} projects in view carry open flags (${int(data.data_quality.rows_high_severity)} high); included, not excluded.`}>
                Data-quality caveat
              </Check>
              <Check ok={!!genieSql} detail={genieSql ? "Showing the SQL Genie wrote for your last question." : "Showing the SQL behind the view above."}>
                Query / intermediate steps
              </Check>
            </div>
            <div className="mt">
              <SqlBlock sql={genieSql || data.evidence.by_region} comment={genieSql ? "Generated by Genie" : "Investment by region (certified table)"} />
            </div>
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
