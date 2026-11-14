import React, { useEffect, useMemo, useState } from "react";
import { useApp } from "../App.jsx";
import { get, invalidate, post } from "../api.js";
import { int, musd, title } from "../format.js";
import { DataTable, ErrorBox, EvidenceDrawer, Loading, StepLine, Tag, useApi } from "../ui.jsx";

const ASSESS = { Improving: "green", Deteriorating: "red", Stable: "grey", Up: "blue", Down: "blue" };

function fmt(v, unit) {
  if (v === null || v === undefined) return "–";
  if (unit === "USD M") return musd(v);
  if (unit === "%") return `${Number(v).toFixed(1)}%`;
  if (unit === "projects") return int(v);
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
}
const pctTxt = (v) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(1)}%`);

export default function Monthly() {
  const { toast } = useApp();
  const [tick, setTick] = useState(0);
  const { data: st, error, loading } = useApi("/api/monthly/status", [tick]);
  const months = st?.months || [];
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [dim, setDim] = useState("Portfolio");
  const [evidence, setEvidence] = useState(null);

  useEffect(() => {
    if (months.length >= 2 && !a) {
      setA(months[months.length - 2]);
      setB(months[months.length - 1]);
    }
  }, [months, a]);

  return (
    <>
      <div className="eyebrow blue">Monthly history</div>
      <div className="page-head">
        <div>
          <h1 className="title">Month-over-month trends</h1>
          <div className="subtitle">Each reporting month is a certified snapshot; a corrected re-upload replaces only its own month</div>
        </div>
        <div className="actions">
          <button className="btn" disabled={!st} onClick={() => setEvidence(st.evidence)}>Evidence / SQL</button>
        </div>
      </div>
      {error && <ErrorBox error={error} />}
      {loading && !st && <Loading />}
      {st && months.length < 2 && (
        <div className="card">
          <h3>Not enough history yet</h3>
          <p className="muted">
            {months.length} month(s) loaded in <code>{st.schema}</code>. Load at least two months below, or run the
            <code> run_monthly_pipeline</code> job.
          </p>
        </div>
      )}
      {st && months.length >= 2 && a && b && (
        <Compare months={months} a={a} b={b} dim={dim} setA={setA} setB={setB} setDim={setDim} dims={st.dimensions} onEvidence={setEvidence} />
      )}
      {st && <Upload status={st} onDone={() => { invalidate("/api/monthly"); setTick((t) => t + 1); }} toast={toast} />}
      {evidence && <EvidenceDrawer items={evidence} onClose={() => setEvidence(null)} />}
    </>
  );
}

function Compare({ months, a, b, dim, setA, setB, setDim, dims, onEvidence }) {
  const cmp = useApi(`/api/monthly/compare?a=${a}&b=${b}&dimension=${encodeURIComponent(dim)}`);
  const ser = useApi("/api/monthly/series");
  const chg = useApi(`/api/monthly/changes?a=${a}&b=${b}`);
  const [kpi, setKpi] = useState("R01");
  const [ctype, setCtype] = useState("");
  const [kpiDim, setKpiDim] = useState("");
  const detail = useApi(ctype ? `/api/monthly/changes?a=${a}&b=${b}&change_type=${ctype}` : null);

  const rows = cmp.data?.rows || [];
  const good = rows.filter((r) => r.assessment === "Improving").sort((x, y) => Math.abs(y.change_pct || 0) - Math.abs(x.change_pct || 0));
  const bad = rows.filter((r) => r.assessment === "Deteriorating").sort((x, y) => Math.abs(y.change_pct || 0) - Math.abs(x.change_pct || 0));
  const kpis = useMemo(() => {
    const m = new Map();
    (ser.data?.rows || []).forEach((r) => m.set(r.kpi_id, { id: r.kpi_id, name: r.kpi_name, unit: r.unit }));
    return [...m.values()];
  }, [ser.data]);
  const line = (ser.data?.rows || []).filter((r) => r.kpi_id === kpi);
  const unit = kpis.find((k) => k.id === kpi)?.unit;
  const dimKpis = [...new Set(rows.map((r) => r.kpi_name))].sort();
  const pickedDimKpi = kpiDim || dimKpis[0];

  const kpiCols = [
    { key: "kpi_name", label: "Measure", strong: true },
    { key: "value_a", label: a, num: true, render: (v, r) => fmt(v, r.unit) },
    { key: "value_b", label: b, num: true, render: (v, r) => fmt(v, r.unit) },
    { key: "change_pct", label: "Change", num: true, render: (v) => pctTxt(v) },
  ];

  return (
    <>
      <div className="card">
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <span className="small muted">Compare</span>
          <select value={a} onChange={(e) => setA(e.target.value)} aria-label="From month">
            {months.map((m) => <option key={m}>{m}</option>)}
          </select>
          <span className="small muted">with</span>
          <select value={b} onChange={(e) => setB(e.target.value)} aria-label="To month">
            {months.map((m) => <option key={m}>{m}</option>)}
          </select>
          <span className="small muted">by</span>
          <select value={dim} onChange={(e) => setDim(e.target.value)} aria-label="Breakdown">
            {dims.map((d) => <option key={d}>{d}</option>)}
          </select>
          <span className="small muted" style={{ marginLeft: "auto" }}>{months.length} months loaded: {months[0]} to {months[months.length - 1]}</span>
        </div>
      </div>

      {cmp.error && <ErrorBox error={cmp.error} />}
      {cmp.loading && <Loading label="Comparing months…" />}
      {cmp.data && dim === "Portfolio" && (
        <>
          <div className="grid g3 mt">
            <div className="card"><div className="kpi-label">Measures improving</div><div className="kpi-value" style={{ color: "var(--green, #1f8a4c)" }}>{good.length}</div></div>
            <div className="card"><div className="kpi-label">Measures deteriorating</div><div className="kpi-value red">{bad.length}</div></div>
            <div className="card"><div className="kpi-label">Stable or neutral</div><div className="kpi-value">{rows.length - good.length - bad.length}</div></div>
          </div>
          <div className="grid g2 mt">
            <div className="card">
              <div className="card-head"><h3>🟢 Going well</h3><button className="link" onClick={() => onEvidence({ comparison: cmp.data.evidence })}>SQL</button></div>
              <DataTable columns={kpiCols} rows={good} empty="Nothing improved materially" />
            </div>
            <div className="card">
              <div className="card-head"><h3>🔴 Needs attention</h3><button className="link" onClick={() => onEvidence({ comparison: cmp.data.evidence })}>SQL</button></div>
              <DataTable columns={kpiCols} rows={bad} empty="Nothing deteriorated materially" />
            </div>
          </div>
        </>
      )}
      {cmp.data && dim !== "Portfolio" && (
        <div className="card mt">
          <div className="card-head">
            <h3>{dim} breakdown</h3>
            <select value={pickedDimKpi} onChange={(e) => setKpiDim(e.target.value)} aria-label="Measure">
              {dimKpis.map((k) => <option key={k}>{k}</option>)}
            </select>
          </div>
          <DataTable
            columns={[
              { key: "dimension_value", label: dim, strong: true },
              { key: "value_a", label: a, num: true, render: (v, r) => fmt(v, r.unit) },
              { key: "value_b", label: b, num: true, render: (v, r) => fmt(v, r.unit) },
              { key: "change_pct", label: "Change", num: true, render: (v) => pctTxt(v) },
              { key: "assessment", label: "Assessment", render: (v) => (v ? <Tag color={ASSESS[v]}>{v}</Tag> : "–") },
            ]}
            rows={rows.filter((r) => r.kpi_name === pickedDimKpi).sort((x, y) => Math.abs(y.change_pct || 0) - Math.abs(x.change_pct || 0))}
          />
        </div>
      )}

      <div className="card mt">
        <div className="card-head">
          <h3>Trend across all months</h3>
          <select value={kpi} onChange={(e) => setKpi(e.target.value)} aria-label="Measure">
            {kpis.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
          </select>
        </div>
        {ser.loading && <Loading />}
        {line.length > 0 && <StepLine data={line} xKey="month_label" yKey="value" format={(v) => fmt(v, unit)} />}
      </div>

      <div className="card mt">
        <div className="card-head">
          <h3>Why it moved: project changes {a} → {b}</h3>
          {chg.data && <button className="link" onClick={() => onEvidence({ summary: chg.data.evidence, ...(detail.data ? { detail: detail.data.detail_evidence } : {}) })}>SQL</button>}
        </div>
        {chg.loading && <Loading />}
        {chg.error && <ErrorBox error={chg.error} />}
        {chg.data && (
          <DataTable
            onRowClick={(r) => setCtype(r.change_type)}
            columns={[
              { key: "change_type", label: "Change", strong: true, render: (v) => title(v.toLowerCase()) },
              { key: "impact", label: "Impact", render: (v) => <Tag color={v === "Positive" ? "green" : v === "Negative" ? "red" : "grey"}>{v}</Tag> },
              { key: "projects", label: "Projects", num: true },
              { key: "amount_musd", label: "Amount", num: true },
            ]}
            rows={chg.data.summary}
            empty="No project changes between these months"
          />
        )}
        {ctype && (
          <div className="mt">
            <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
              {title(ctype.toLowerCase())}: projects <button className="link" onClick={() => setCtype("")}>clear</button>
            </div>
            {detail.loading && <Loading />}
            {detail.data && <DataTable rows={detail.data.detail} pageSize={10} />}
          </div>
        )}
      </div>
    </>
  );
}

function Upload({ status, onDone, toast }) {
  const [month, setMonth] = useState("");
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const runs = useApi(status.job_configured ? "/api/monthly/runs" : null, [result]);
  const valid = /^20\d\d-(0[1-9]|1[0-2])$/.test(month);
  const loadedMonths = new Set((status.loads || []).map((l) => l.month));

  const submit = async () => {
    setBusy(true);
    try {
      const payload = await Promise.all(
        [...files].map(
          (f) =>
            new Promise((res, rej) => {
              const r = new FileReader();
              r.onload = () => res({ name: f.name, content_base64: String(r.result).split(",")[1] });
              r.onerror = rej;
              r.readAsDataURL(f);
            }),
        ),
      );
      const out = await post("/api/monthly/upload", { month, files: payload });
      setResult(out);
      toast(out.run_id ? `Uploaded; pipeline run ${out.run_id} started` : "Uploaded");
      invalidate("/api/monthly/runs");
    } catch (e) {
      toast(`Upload failed: ${e.message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid g2 mt">
      <div className="card">
        <div className="card-head"><h3>Load a new month</h3></div>
        <p className="small muted" style={{ marginTop: 0 }}>
          Upload the month's projects and monitoring CSVs. The pipeline checks them against the data contracts, certifies the month
          and refreshes the trends (about 10–15 minutes per month). Uploading again for a loaded month replaces only that month;
          the earlier files stay in Raw for audit.
        </p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <input placeholder="Reporting month, e.g. 2026-11" value={month} onChange={(e) => setMonth(e.target.value.trim())} style={{ width: 210 }} />
          <input type="file" accept=".csv" multiple onChange={(e) => setFiles(e.target.files || [])} />
        </div>
        {month && !valid && <div className="error mt">Month must look like 2026-11.</div>}
        {valid && loadedMonths.has(month) && <div className="notice mt"><span>⚠</span><span>{month} is already loaded. Uploading replaces {month} with these files.</span></div>}
        {!status.job_configured && <div className="notice mt"><span>ℹ</span><span>Pipeline job not configured (IFC_MONTHLY_JOB_ID): files will be uploaded but not processed.</span></div>}
        <div className="mt">
          <button className="btn dark" disabled={busy || !valid || !files.length} onClick={submit}>
            {busy ? "Uploading…" : "Upload and run pipeline"}
          </button>
        </div>
        {result && <p className="small mt">Uploaded {result.uploaded.join(", ")} to <code>{result.folder}</code>{result.run_id ? `; run ${result.run_id} started.` : "."}</p>}
      </div>
      <div className="card">
        <div className="card-head">
          <h3>Pipeline runs</h3>
          <button className="link" onClick={() => { invalidate("/api/monthly"); onDone(); }}>Refresh</button>
        </div>
        {!status.job_configured && <div className="empty">No job configured</div>}
        {runs.data && (
          <DataTable
            columns={[
              { key: "run_id", label: "Run", render: (v, r) => <a href={r.url} target="_blank" rel="noreferrer">{v}</a> },
              { key: "started_ms", label: "Started", render: (v) => (v ? new Date(v).toLocaleString() : "–") },
              { key: "state", label: "State", render: (v) => <Tag color={v === "SUCCESS" ? "green" : v === "FAILED" ? "red" : "blue"}>{v || "–"}</Tag> },
            ]}
            rows={runs.data}
            empty="No runs yet"
          />
        )}
        <div className="small" style={{ fontWeight: 600, margin: "14px 0 6px" }}>Loaded files</div>
        <DataTable rows={status.loads} pageSize={6} empty="No months loaded" />
        <div className="small" style={{ fontWeight: 600, margin: "14px 0 6px" }}>Latest file checks (schema gate)</div>
        <DataTable rows={status.gate} pageSize={6} empty="No checks yet" />
      </div>
    </div>
  );
}
