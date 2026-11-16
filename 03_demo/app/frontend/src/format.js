// Amounts are USD millions throughout the data (A16).
export function musd(v, { digits } = {}) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "–";
  const n = Number(v);
  if (Math.abs(n) >= 1000) {
    const d = digits ?? 2;
    return `$${(n / 1000).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d })}B`;
  }
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: digits ?? 0 })}M`;
}

export const musdFull = (v) =>
  v === null || v === undefined ? "–" : `$${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}M`;

export const int = (v) => (v === null || v === undefined ? "–" : Number(v).toLocaleString("en-US"));

export const pct = (v, d = 0) => (v === null || v === undefined ? "–" : `${(Number(v) * 100).toFixed(d)}%`);

function parse(v) {
  const s = String(v).replace(" ", "T");
  return new Date(/Z|[+-]\d\d:?\d\d$/.test(s) || s.length <= 10 ? s : s + "Z");
}

export function date(v) {
  if (!v) return "–";
  const d = parse(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

// "13 Nov 2026, 22:05" in the viewer's time zone
export function dateTime(v) {
  if (!v) return "–";
  const d = parse(v);
  if (Number.isNaN(d.getTime())) return String(v);
  return `${d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}, ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

// Full timestamp with time zone, for tooltips
export function dateTimeFull(v) {
  if (!v) return "";
  const d = parse(v);
  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString("en-GB", { dateStyle: "full", timeStyle: "long" });
}

export function ago(v) {
  if (!v) return "";
  const s = (Date.now() - parse(v).getTime()) / 1000;
  if (Number.isNaN(s)) return "";
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  const d = Math.round(s / 86400);
  return d === 1 ? "1 day ago" : `${d} days ago`;
}

export const title = (s) => (s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
