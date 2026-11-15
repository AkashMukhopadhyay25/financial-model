import React, { useEffect, useState } from "react";
import { createPortal } from "react-dom";
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
  const [sort, setSort] = useState(null); // { key, dir: 1 | -1 }
  useEffect(() => setShown(pageSize || maxRows), [rows, pageSize, maxRows]);
  if (!rows?.length) return <div className="empty">{empty}</div>;
  const cols = columns || Object.keys(rows[0]).map((k) => ({ key: k, label: title(k), num: typeof rows[0][k] === "number" }));
  const sortable = (c) => c.sortable !== false && c.label;
  const valueOf = (c, r) => (c.sortValue ? c.sortValue(r) : c.key === "needs_review" ? dqRank(r) : r[c.key]);
  const clickSort = (c) => {
    if (!sortable(c)) return;
    // numbers start largest-first, text A-Z; a second click flips the order
    const first = c.num || c.key === "needs_review" || c.sortDesc ? -1 : 1; // data quality: most serious first
    setSort((s) => (s && s.key === c.key ? { key: c.key, dir: -s.dir } : { key: c.key, dir: first }));
  };
  let view = rows;
  if (sort) {
    const c = cols.find((x) => x.key === sort.key);
    view = [...rows].sort((a, b) => compareValues(valueOf(c, a), valueOf(c, b)) * sort.dir);
  }
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={`${c.num ? "num" : ""} ${sortable(c) ? "sortable" : ""} ${sort?.key === c.key ? "sorted" : ""}`}
                  onClick={() => clickSort(c)} aria-sort={sort?.key === c.key ? (sort.dir > 0 ? "ascending" : "descending") : undefined}>
                {c.label}
                {sortable(c) && <span className="sort-ic">{sort?.key === c.key ? (sort.dir > 0 ? "▲" : "▼") : "↕"}</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {view.slice(0, Math.min(shown, maxRows)).map((r, i) => (
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

// Missing values always sort last; numbers numerically; text alphabetically (A-Z, numbers inside names in order).
function compareValues(a, b) {
  const na = a === null || a === undefined || a === "", nb = b === null || b === undefined || b === "";
  if (na || nb) return na === nb ? 0 : na ? 1 : -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), "en", { numeric: true, sensitivity: "base" });
}

// Data quality sorts by severity: clean 0, warning 1, high 2
function dqRank(r) {
  return !r.needs_review ? 0 : r.dq_max_severity === "high" ? 2 : 1;
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

// Data-quality flag codes (contracts/*.yml) -> short reason shown in tables. High-severity codes sort first.
const DQ_REASONS = {
  "P-F01": "Region renamed", "P-F02": "Under-allocated", "P-F03": "Over-allocated", "P-F04": "Signed before approval",
  "P-F05": "Invested, not signed", "P-F06": "Outdated record", "P-F07": "Board date passed", "P-F08": "No Board date",
  "P-F09": "Status/date conflict", "P-F10": "Country code conflict", "P-F11": "No description", "P-F12": "Outside emerging markets",
  "P-F13": "Invested before signed", "M-F01": "Project number mismatch", "M-F02": "Dropped but monitored",
  "M-F03": "Over-disbursed", "M-F04": "Performance conflict", "M-F05": "Disbursement date conflict",
  "M-F06": "Disbursement status conflict", "M-F07": "Review days conflict", "M-F08": "Review overdue", "M-F09": "Client identity conflict",
};
const DQ_HIGH = new Set(["P-F03", "P-F09", "P-F10", "M-F01", "M-F02", "M-F03", "M-F04", "M-F05", "M-F06", "M-F09"]);

// Tag naming why a project is flagged; hover lists every reason in full. Flagged rows stay in every figure.
export function DqTag({ needs, severity, ids, messages }) {
  const [pos, setPos] = useState(null);
  if (!needs) return <Tag color="green">Clean</Tag>;
  const codes = String(ids || "").split(",").map((c) => c.trim()).filter(Boolean)
    .sort((a, b) => (DQ_HIGH.has(b) ? 1 : 0) - (DQ_HIGH.has(a) ? 1 : 0));
  const msgs = String(messages || "").split(" | ").filter(Boolean);
  const first = codes[0] ? DQ_REASONS[codes[0]] || codes[0] : (msgs[0] || "Data issue").split(/[:,]/)[0];
  const more = Math.max(codes.length, msgs.length) - 1;
  const show = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    setPos({ x: Math.min(window.innerWidth - 330, Math.max(10, r.left)), y: r.bottom + 6 });
  };
  return (
    <span className="dqtag" onMouseEnter={show} onMouseLeave={() => setPos(null)} onFocus={show} onBlur={() => setPos(null)} tabIndex={0}>
      <Tag color={severity === "high" ? "red" : "amber"}>
        {first}{more > 0 && <b className="dq-more">+{more}</b>}
      </Tag>
      {pos && msgs.length > 0 && createPortal(
        // rendered on <body>: the page frame's backdrop-filter would otherwise offset position: fixed
        <span className="dq-pop" style={{ left: pos.x, top: pos.y }} role="tooltip">
          <span className="dq-pop-title">{severity === "high" ? "High-severity data issue" : "Data issue"} · included in the figures</span>
          {msgs.map((m, i) => <span key={i} className="dq-pop-item">{m}</span>)}
        </span>,
        document.body,
      )}
    </span>
  );
}

// ---------------------------------------------------------------- charts (hand-drawn SVG, no chart library)
export function BarChart({ data, labelKey, valueKey, format = musd, height = 220, highlight = "max", color = "#2f66f6" }) {
  const [hover, setHover] = useState(null);
  if (!data?.length) return <div className="empty">No data</div>;
  const W = 520, top = 34, H = height, gap = 14;
  const vals = data.map((d) => Number(d[valueKey]) || 0);
  const max = Math.max(...vals) || 1;
  const bw = (W - gap * (data.length - 1)) / data.length;
  const hi = hover ?? (highlight === "max" ? vals.indexOf(max) : null);
  const maxChars = Math.max(6, Math.floor(bw / 6.2));
  const stripe = `stripe-${color.replace("#", "")}`;
  const barTop = (v) => H - (v / max) * (H - top);
  const tip = hi != null ? format(vals[hi]) : "";
  const tipW = Math.max(56, tip.length * 7.2 + 18);
  const tipX = hi != null ? Math.min(W - tipW / 2, Math.max(tipW / 2, hi * (bw + gap) + bw / 2)) : 0;
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H + 44}`} role="img" onMouseLeave={() => setHover(null)}>
        <defs>
          <pattern id={stripe} width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="7" height="7" fill={color} opacity=".55" />
            <rect width="4" height="7" fill={color} opacity=".9" />
          </pattern>
        </defs>
        {data.map((d, i) => {
          const x = i * (bw + gap);
          const lines = wrapLabel(String(d[labelKey] ?? ""), maxChars);
          return (
            <g key={i} onMouseEnter={() => setHover(i)} style={{ cursor: "pointer" }}>
              <rect x={x} y={0} width={bw} height={H} fill="transparent" />
              <rect x={x} y={barTop(vals[i])} width={bw} height={Math.max(1, H - barTop(vals[i]))} rx="8"
                    fill={i === hi ? color : `url(#${stripe})`} />
              <text x={x + bw / 2} y={H + 17} textAnchor="middle" fontWeight={i === hi ? 600 : 400}>
                {lines.map((l, j) => (
                  <tspan key={j} x={x + bw / 2} dy={j === 0 ? 0 : 14}>{l}</tspan>
                ))}
              </text>
            </g>
          );
        })}
        {hi != null && (
          <g pointerEvents="none">
            <rect x={tipX - tipW / 2} y={Math.max(0, barTop(vals[hi]) - 29)} width={tipW} height="22" rx="11" fill="#0f1222" />
            <text x={tipX} y={Math.max(0, barTop(vals[hi]) - 29) + 15} textAnchor="middle" style={{ fill: "#fff", fontSize: 12, fontWeight: 600 }}>
              {tip}
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}

// Split a label into at most two lines, as evenly as possible at a space; "…" only if a single word is too long.
function wrapLabel(text, maxChars) {
  if (text.length <= maxChars) return [text];
  const words = text.split(" ");
  let best = null;
  for (let k = 1; k < words.length; k++) {
    const a = words.slice(0, k).join(" "), b = words.slice(k).join(" ");
    const score = Math.max(a.length, b.length);
    if (!best || score < best.score) best = { score, lines: [a, b] };
  }
  const lines = best ? best.lines : [text];
  return lines.map((l) => (l.length > maxChars + 2 ? l.slice(0, maxChars + 1) + "…" : l));
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

// Column chart by year: value axis with gridlines, every year labelled, hover label above the column.
// `partialFrom`: the year that is still in progress (drawn hatched, labelled with `partialLabel`).
export function YearColumns({ data, xKey, yKey, format = musd, height = 230, partialYear, partialLabel, color = "#2f66f6" }) {
  const [hover, setHover] = useState(null);
  if (!data?.length) return <div className="empty">No data</div>;
  const W = 560, H = height, left = 46, top = 30, bottom = 26;
  const plotH = H - top - bottom, plotW = W - left;
  const vals = data.map((d) => Number(d[yKey]) || 0);
  const max = Math.max(...vals) || 1;
  const step = niceStep(max / 4);
  const yMax = Math.ceil(max / step) * step;
  const ticks = Array.from({ length: Math.round(yMax / step) + 1 }, (_, i) => i * step);
  const slot = plotW / data.length, bw = Math.min(30, slot * 0.62);
  const y = (v) => top + plotH - (v / yMax) * plotH;
  const fullVals = vals.filter((_, i) => String(data[i][xKey]) !== String(partialYear));
  const peak = vals.indexOf(Math.max(...fullVals));
  const active = hover ?? peak;
  const ax = left + (active + 0.5) * slot;
  const isPartial = (i) => String(data[i][xKey]) === String(partialYear);
  const tip = `${data[active][xKey]}${isPartial(active) && partialLabel ? ` (${partialLabel})` : ""} · ${format(vals[active])}`;
  const tipW = Math.max(90, tip.length * 6.6);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" onMouseLeave={() => setHover(null)}>
        <defs>
          <pattern id="yc-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill={color} opacity=".18" />
            <rect width="2.5" height="6" fill={color} opacity=".55" />
          </pattern>
        </defs>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={left} x2={W} y1={y(t)} y2={y(t)} stroke="#eef0f5" />
            <text x={left - 8} y={y(t) + 4} textAnchor="end">{t === 0 ? "0" : format(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = left + i * slot + (slot - bw) / 2;
          const h = Math.max(1, y(0) - y(vals[i]));
          return (
            <g key={i} onMouseEnter={() => setHover(i)} style={{ cursor: "pointer" }}>
              <rect x={left + i * slot} y={top} width={slot} height={plotH} fill="transparent" />
              <rect x={x} y={y(vals[i])} width={bw} height={h} rx="5"
                    fill={isPartial(i) ? "url(#yc-hatch)" : color} opacity={isPartial(i) ? 1 : i === active ? 1 : 0.32} />
              <text x={left + (i + 0.5) * slot} y={H - 8} textAnchor="middle" fontWeight={i === active ? 600 : 400}>
                {`'${String(d[xKey]).slice(-2)}`}
              </text>
            </g>
          );
        })}
        <g pointerEvents="none">
          <rect x={Math.min(W - tipW, Math.max(left, ax - tipW / 2))} y={Math.max(0, y(vals[active]) - 28)} width={tipW} height="21" rx="10" fill="#0f1222" />
          <text className="tip" x={Math.min(W - tipW / 2, Math.max(left + tipW / 2, ax))} y={Math.max(0, y(vals[active]) - 28) + 14.5}
                textAnchor="middle" style={{ fill: "#fff", fontSize: 11.5 }}>{tip}</text>
        </g>
      </svg>
    </div>
  );
}

function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const n = raw / p;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p;
}

export function MiniBars({ data, xKey, yKey, color = "#2f66f6", format = (v) => int(v) }) {
  const [hover, setHover] = useState(null);
  if (!data?.length) return null;
  const values = data.map((d) => Number(d[yKey]) || 0);
  const max = Math.max(...values) || 1;
  const active = hover ?? data.length - 1; // latest year emphasised; the label shows only while hovering
  return (
    <div className="minibars" onMouseLeave={() => setHover(null)}>
      {hover != null && (
        <div className="minibars-tip" style={{ left: `${Math.min(84, Math.max(16, ((hover + 0.5) / data.length) * 100))}%` }}>
          <b>{data[hover][xKey]}</b> {format(values[hover])}
        </div>
      )}
      <div style={{ display: "flex", gap: 4, alignItems: "flex-end", height: 34 }}>
        {data.map((d, i) => (
          <div key={i} className="minibar" onMouseEnter={() => setHover(i)} tabIndex={0} onFocus={() => setHover(i)} onBlur={() => setHover(null)}
               aria-label={`${d[xKey]}: ${format(values[i])}`}>
            <div style={{ height: `${Math.max(4, (values[i] / max) * 100)}%`, background: color, opacity: i === active ? 1 : 0.35 }} />
          </div>
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
