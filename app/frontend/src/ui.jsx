import React, { useEffect, useState } from "react";
import { get } from "./api.js";
import { int, musd, title } from "./format.js";

// ---------------------------------------------------------------- data hook
export function useApi(path, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  useEffect(() => {
    let live = true;
    if (!path) return undefined;
    setState((s) => ({ ...s, loading: true, error: null }));
    get(path)
      .then((data) => live && setState({ data, error: null, loading: false }))
      .catch((error) => live && setState({ data: null, error, loading: false }));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps]);
  return state;
}

export function Loading({ label = "Loading certified data…" }) {
  return (
    <div className="thinking">
      <span className="spinner" /> {label}
    </div>
  );
}

export function ErrorBox({ error }) {
  return <div className="error">Could not load data: {String(error?.message || error)}</div>;
}

// ---------------------------------------------------------------- primitives
export const Tag = ({ color = "grey", caps, children, title: t }) => (
  <span className={`tag ${color}${caps ? " caps" : ""}`} title={t}>
    {children}
  </span>
);

export function Stripe({ value = 1, color = "var(--blue)", height }) {
  const w = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="stripe" style={height ? { height } : undefined}>
      <span style={{ width: `${w}%`, "--c": color }} />
    </div>
  );
}

// Whole-number percentages that always add up to 100 (largest-remainder method).
export function wholePercents(values) {
  const total = values.reduce((a, v) => a + v, 0);
  if (!total) return values.map(() => 0);
  const raw = values.map((v) => (100 * v) / total);
  const out = raw.map(Math.floor);
  let left = 100 - out.reduce((a, v) => a + v, 0);
  raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]).forEach(([, i]) => { if (left > 0) { out[i] += 1; left -= 1; } });
  return out;
}

// Proportional bar: each segment's width is its share of the total. Hover a segment for the exact value.
export function SplitBar({ segments, format = (v) => int(v), legend = false, height = 8 }) {
  const segs = (segments || []).filter((x) => Number(x.value) > 0);
  const total = segs.reduce((a, x) => a + Number(x.value), 0);
  if (!total) return <div className="stripe" style={{ height }} />;
  const pcts = wholePercents(segs.map((x) => Number(x.value)));
  return (
    <div>
      <div className="splitbar" style={{ height }}>
        {segs.map((x) => (
          <span key={x.label} style={{ flex: Number(x.value), "--c": x.color }}
                title={`${x.label}: ${format(x.value)} (${pcts[segs.indexOf(x)]}%)`} />
        ))}
      </div>
      {legend && (
        <div className="splitbar-legend">
          {segs.map((x) => (
            <span key={x.label} title={`${x.label}: ${format(x.value)}`}><i style={{ background: x.color }} />{x.label}<em className="pct">&nbsp;{pcts[segs.indexOf(x)]}%</em></span>
          ))}
        </div>
      )}
    </div>
  );
}

export function Dots({ n, of = 12, color }) {
  const on = Math.round(Math.min(of, n));
  return (
    <div className="dots" aria-hidden>
      {Array.from({ length: of }, (_, i) => (
        <i key={i} style={{ background: color, opacity: i < on ? 1 - i * (0.5 / of) : 0.18 }} />
      ))}
    </div>
  );
}

export function Check({ ok, warn, children, detail }) {
  return (
    <div className="check">
      <span className={`ic ${ok ? "ok" : warn ? "warn" : ""}`}>
        {ok ? (
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M1.5 5.2l2.2 2.2L8.5 2.6" stroke="currentColor" strokeWidth="1.6" fill="none" />
          </svg>
        ) : warn ? (
          "!"
        ) : null}
      </span>
      <div style={{ flex: 1 }}>{children}</div>
      {detail && <Info text={detail} />}
    </div>
  );
}

// Small (i) icon: the explanation shows on hover / focus instead of taking space on the page.
export function Info({ text, align = "right" }) {
  return (
    <span className={`info info-${align}`} tabIndex={0} aria-label={typeof text === "string" ? text : "More information"}>
      <svg width="13" height="13" viewBox="0 0 14 14" aria-hidden>
        <circle cx="7" cy="7" r="6.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
        <path d="M7 6.2v3.8M7 4.1v.1" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      </svg>
      <span className="info-pop" role="tooltip">{text}</span>
    </span>
  );
}

// Compact "label value" chips used instead of sentences.
export function Stats({ items }) {
  const shown = items.filter((i) => i && i.value !== null && i.value !== undefined && i.value !== 0 && i.value !== "0");
  return (
    <div className="stats">
      {shown.map((i) => (
        <span key={i.label} className={`stat ${i.color || ""}`}>
          <b>{i.value}</b> {i.label}
        </span>
      ))}
    </div>
  );
}

export const OkIcon = () => (
  <svg className="ok-ic" width="18" height="18" viewBox="0 0 18 18">
    <circle cx="9" cy="9" r="8" fill="none" stroke="currentColor" strokeWidth="1.4" />
    <path d="M5.3 9.2l2.4 2.4 5-5" stroke="currentColor" strokeWidth="1.5" fill="none" />
  </svg>
);

export const SparkIcon = ({ size = 12, color = "currentColor" }) => (
  <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden>
    <path d="M6 0l1.3 4.7L12 6l-4.7 1.3L6 12l-1.3-4.7L0 6l4.7-1.3z" fill={color} />
  </svg>
);

export function SqlBlock({ sql, comment = "Certified SQL" }) {
  if (!sql) return <pre className="code"><span className="cm">-- No SQL available</span></pre>;
  return (
    <pre className="code">
      <span className="cm">-- {comment}</span>
      {"\n"}
      {sql}
    </pre>
  );
}

// ---------------------------------------------------------------- table
export function DataTable({ columns, rows, onRowClick, empty = "No rows", maxRows = 200, pageSize }) {
  const [shown, setShown] = useState(pageSize || maxRows);
  useEffect(() => setShown(pageSize || maxRows), [rows, pageSize, maxRows]);
  if (!rows?.length) return <div className="empty">{empty}</div>;
  const cols = columns || Object.keys(rows[0]).map((k) => ({ key: k, label: title(k), num: typeof rows[0][k] === "number" }));
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={c.num ? "num" : ""}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, Math.min(shown, maxRows)).map((r, i) => (
            <tr key={i} className={onRowClick ? "clickable" : ""} onClick={onRowClick ? () => onRowClick(r) : undefined}>
              {cols.map((c) => (
                <td key={c.key} className={`${c.num ? "num" : ""} ${c.strong ? "strong" : ""}`}>
                  {c.render ? c.render(r[c.key], r) : fmtCell(r[c.key], c.key)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > Math.min(shown, maxRows) && (
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 10 }} className="no-print">
          <span className="small muted">Showing {int(Math.min(shown, maxRows))} of {int(rows.length)} rows</span>
          {shown < maxRows && (
            <>
              <button className="btn small" onClick={() => setShown((n) => n + (pageSize || 10))}>Show more</button>
              <button className="link" onClick={() => setShown(maxRows)}>Show all</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function fmtCell(v, key) {
  if (v === null || v === undefined) return "–";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (typeof v === "number") {
    if (/musd/.test(key)) return musd(v);
    return Number.isInteger(v) ? int(v) : v.toLocaleString("en-US", { maximumFractionDigits: 2 });
  }
  return String(v);
}

export function StatusTag({ value }) {
  const map = { Active: "green", Closed: "grey", Pending: "blue", Dropped: "red", "Past Due": "red", Watchlist: "amber", Performing: "green" };
  return <Tag color={map[value] || "grey"}>{value || "–"}</Tag>;
}

export function DqTag({ needs, severity }) {
  if (!needs) return <Tag color="green">Clean</Tag>;
  return <Tag color={severity === "high" ? "red" : "amber"} title="Open data-quality issue (included, not excluded)">{severity === "high" ? "High DQ flag" : "DQ flag"}</Tag>;
}

// ---------------------------------------------------------------- charts (hand-drawn SVG, no chart library)
export function BarChart({ data, labelKey, valueKey, format = musd, height = 220, highlight = "max", color = "#2f66f6" }) {
  const [hover, setHover] = useState(null);
  if (!data?.length) return <div className="empty">No data</div>;
  const W = 520, H = height, pad = 26, gap = 14;
  const max = Math.max(...data.map((d) => Number(d[valueKey]) || 0)) || 1;
  const bw = (W - gap * (data.length - 1)) / data.length;
  const hi = hover ?? (highlight === "max" ? data.findIndex((d) => Number(d[valueKey]) === max) : null);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H + 40}`} role="img">
        <defs>
          <pattern id={`stripe-${color.replace("#", "")}`} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="7" height="7" fill={color} opacity=".55" />
            <rect width="4" height="7" fill={color} opacity=".9" />
          </pattern>
        </defs>
        {data.map((d, i) => {
          const v = Number(d[valueKey]) || 0;
          const h = (v / max) * (H - pad);
          const x = i * (bw + gap);
          const active = i === hi;
          return (
            <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x} y={H - h} width={bw} height={h} rx="8" fill={active ? color : `url(#stripe-${color.replace("#", "")})`} />
              {active && (
                <g>
                  <rect x={Math.max(0, x + bw / 2 - 70)} y={H - h - 26} width="140" height="20" rx="10" fill="#fff" stroke="#e9ecf3" />
                  <text className="tip" x={Math.max(70, x + bw / 2)} y={H - h - 12} textAnchor="middle">
                    {short(d[labelKey], 14)} · {format(v)}
                  </text>
                </g>
              )}
              <text x={x + bw / 2} y={H + 18} textAnchor="middle">
                {short(d[labelKey], Math.max(6, Math.floor(bw / 6)))}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function StepLine({ data, xKey, yKey, format = musd, height = 220 }) {
  const [hover, setHover] = useState(null);
  if (!data?.length) return <div className="empty">No data</div>;
  const W = 520, H = height, top = 20;
  const ys = data.map((d) => Number(d[yKey]) || 0);
  const max = Math.max(...ys) || 1;
  const step = W / data.length;
  const y = (v) => H - (v / max) * (H - top);
  let path = `M0 ${y(ys[0])}`;
  ys.forEach((v, i) => {
    path += ` L${i * step} ${y(v)} L${(i + 1) * step} ${y(v)}`;
  });
  const area = `${path} L${W} ${H} L0 ${H} Z`;
  const last = hover ?? ys.indexOf(max);
  const every = Math.ceil(data.length / 7);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H + 30}`} role="img" onMouseLeave={() => setHover(null)}>
        <defs>
          <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#2f66f6" stopOpacity=".22" />
            <stop offset="1" stopColor="#2f66f6" stopOpacity="0" />
          </linearGradient>
        </defs>
        {data.map((d, i) => (
          <line key={i} x1={i * step} x2={i * step} y1={top} y2={H} stroke="#eef0f5" />
        ))}
        <path d={area} fill="url(#area)" />
        <path d={path} fill="none" stroke="#2f66f6" strokeWidth="2.2" />
        {data.map((d, i) => (
          <rect key={i} x={i * step} y={0} width={step} height={H} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
        <circle cx={(last + 0.5) * step} cy={y(ys[last])} r="5" fill="#fff" stroke="#2f66f6" strokeWidth="2" />
        <text className="tip" x={Math.min(W - 60, Math.max(60, (last + 0.5) * step))} y={Math.max(12, y(ys[last]) - 12)} textAnchor="middle">
          {data[last][xKey]} · {format(ys[last])}
        </text>
        {data.map((d, i) =>
          i % every === 0 ? (
            <text key={i} x={(i + 0.5) * step} y={H + 18} textAnchor="middle">
              {d[xKey]}
            </text>
          ) : null,
        )}
      </svg>
    </div>
  );
}

export function MiniBars({ data, xKey, yKey, color = "#2f66f6", format = (v) => int(v) }) {
  if (!data?.length) return null;
  const values = data.map((d) => Number(d[yKey]) || 0);
  const max = Math.max(...values) || 1;
  return (
    <div>
      <div style={{ display: "flex", gap: 4, alignItems: "flex-end", height: 28 }}>
        {data.map((d, i) => (
          <div key={i} title={`${d[xKey]}: ${format(values[i])}`}
               style={{ flex: 1, height: `${Math.max(4, (values[i] / max) * 100)}%`, borderRadius: 3, background: color, opacity: i === data.length - 1 ? 1 : 0.35 }} />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10.5, color: "var(--muted)", marginTop: 4 }}>
        <span>{data[0][xKey]}</span><span>{data[data.length - 1][xKey]}</span>
      </div>
    </div>
  );
}

const short = (s, n) => {
  const t = String(s ?? "");
  return t.length > n ? t.slice(0, n - 1) + "…" : t;
};

// ---------------------------------------------------------------- overlays
export function Modal({ title: t, onClose, children, actions }) {
  useEscape(onClose);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={t}>
        <div className="modal-head">
          <h2>{t}</h2>
          <div className="actions">
            {actions}
            <button className="btn small" onClick={onClose}>Close</button>
          </div>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Drawer({ title: t, onClose, children }) {
  useEscape(onClose);
  return (
    <>
      <div className="drawer-overlay" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={t}>
        <div className="modal-head">
          <h2 style={{ fontSize: 20 }}>{t}</h2>
          <button className="btn small" onClick={onClose}>Close</button>
        </div>
        {children}
      </aside>
    </>
  );
}

function useEscape(fn) {
  useEffect(() => {
    const h = (e) => e.key === "Escape" && fn();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [fn]);
}

// Evidence drawer: one or more SQL statements with labels
export function EvidenceDrawer({ title: t = "Evidence / SQL", items, note, onClose }) {
  return (
    <Drawer title={t} onClose={onClose}>
      {note && <p className="small muted" style={{ marginTop: 0 }}>{note}</p>}
      {Object.entries(items || {}).map(([k, sql]) => (
        <div key={k} style={{ marginBottom: 16 }}>
          <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>{title(k)}</div>
          <SqlBlock sql={sql} />
        </div>
      ))}
    </Drawer>
  );
}

export function AssumptionsDrawer({ ids, onClose }) {
  const { data, error, loading } = useApi("/api/assumptions");
  const rows = (data || []).filter((a) => !ids || ids.includes(a.assumption_id));
  return (
    <Drawer title={ids ? "Assumptions applied" : "Assumptions (ref_assumptions)"} onClose={onClose}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Where a question or the data is ambiguous, the assumption is written down once and applied consistently to every answer, Genie and this app.
      </p>
      {loading && <Loading />}
      {error && <ErrorBox error={error} />}
      {rows.map((a) => (
        <div key={a.assumption_id} className="card" style={{ marginBottom: 10, padding: 14 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <Tag color="blue">{a.assumption_id}</Tag>
            <b>{a.topic}</b>
          </div>
          <p className="small" style={{ margin: "8px 0 0", lineHeight: 1.5 }}>{a.statement}</p>
          {a.rationale && <p className="small muted" style={{ margin: "6px 0 0" }}>Why: {a.rationale}</p>}
        </div>
      ))}
    </Drawer>
  );
}

export function Toast({ message, onDone }) {
  useEffect(() => {
    if (!message) return undefined;
    const t = setTimeout(onDone, 2600);
    return () => clearTimeout(t);
  }, [message, onDone]);
  return message ? <div className="toast">{message}</div> : null;
}
