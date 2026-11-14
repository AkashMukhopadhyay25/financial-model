import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { get } from "./api.js";
import { date } from "./format.js";
import { QuestionLibrary } from "./Genie.jsx";
import { AssumptionsDrawer, Toast } from "./ui.jsx";
import Overview from "./pages/Overview.jsx";
import Portfolio from "./pages/Portfolio.jsx";
import Risk from "./pages/Risk.jsx";
import Clients from "./pages/Clients.jsx";
import EarlyWarning from "./pages/EarlyWarning.jsx";
import Briefing from "./pages/Briefing.jsx";
import Monthly from "./pages/Monthly.jsx";

export const PAGES = [
  { id: "overview", label: "Overview", el: Overview },
  { id: "portfolio", label: "Portfolio analytics", el: Portfolio },
  { id: "risk", label: "Risk & exposure", el: Risk },
  { id: "clients", label: "Client intelligence", el: Clients },
  { id: "early-warning", label: "Early warning", el: EarlyWarning },
  { id: "monthly", label: "Monthly trends", el: Monthly },
  { id: "briefing", label: "Board briefing", el: Briefing },
];

const Ctx = createContext(null);
export const useApp = () => useContext(Ctx);

function parseHash() {
  const [path, query] = window.location.hash.replace(/^#\/?/, "").split("?");
  const params = Object.fromEntries(new URLSearchParams(query || ""));
  return { page: PAGES.some((p) => p.id === path) ? path : "overview", params };
}

export default function App() {
  const [route, setRoute] = useState(parseHash);
  const [library, setLibrary] = useState(null); // null | {id}
  const [assumptions, setAssumptions] = useState(null); // null | {ids}
  const [toast, setToast] = useState("");
  const [health, setHealth] = useState(null);

  useEffect(() => {
    const h = () => setRoute(parseHash());
    window.addEventListener("hashchange", h);
    get("/api/health").then(setHealth).catch(() => setHealth({ ok: false }));
    return () => window.removeEventListener("hashchange", h);
  }, []);

  const nav = useCallback((page, params = {}) => {
    const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString();
    window.location.hash = `/${page}${q ? `?${q}` : ""}`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const ctx = useMemo(
    () => ({
      nav,
      route,
      health,
      openLibrary: (id) => setLibrary({ id: id || null }),
      openAssumptions: (ids) => setAssumptions({ ids: ids || null }),
      toast: setToast,
    }),
    [nav, route, health],
  );
  const Page = PAGES.find((p) => p.id === route.page).el;

  return (
    <Ctx.Provider value={ctx}>
      <div className="shell">
        <Header />
        <Page key={route.page} params={route.params} />
      </div>
      {library && (
        <QuestionLibrary
          openId={library.id}
          onClose={() => setLibrary(null)}
          onAsk={(q) => {
            setLibrary(null);
            nav("portfolio", { q, t: Date.now() });
          }}
        />
      )}
      {assumptions && <AssumptionsDrawer ids={assumptions.ids} onClose={() => setAssumptions(null)} />}
      <Toast message={toast} onDone={() => setToast("")} />
    </Ctx.Provider>
  );
}

function Header() {
  const { nav, route, health } = useApp();
  const [open, setOpen] = useState(null); // "search" | "alerts"
  const { data: ov } = useApiLite("/api/overview");
  const refreshed = ov?.activity?.[0]?.at || ov?.kpis?.reporting_date;
  return (
    <>
      <div className="topbar">
        <div className="brand" onClick={() => nav("overview")}>
          <span className="brand-logo">IFC</span>
          <span>
            IFC <span className="sep">|</span> CFO Intelligence
          </span>
        </div>
        <nav className="nav" aria-label="Pages">
          {PAGES.map((p) => (
            <button key={p.id} className={route.page === p.id ? "active" : ""} onClick={() => nav(p.id)}>
              {p.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="subbar">
        <span className="pill" title={`Reporting date ${ov?.kpis?.reporting_date || ""}`}>
          <span className="dot" /> Data refreshed: {refreshed ? date(refreshed) : "…"}
        </span>
        <button className="icon-btn" aria-label="Search" onClick={() => setOpen(open === "search" ? null : "search")}>
          <svg width="14" height="14" viewBox="0 0 14 14"><circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M9.5 9.5L13 13" stroke="currentColor" strokeWidth="1.5" /></svg>
        </button>
        <button className="icon-btn" aria-label="Alerts" onClick={() => setOpen(open === "alerts" ? null : "alerts")}>
          <svg width="14" height="14" viewBox="0 0 14 14"><path d="M7 1.5a4 4 0 00-4 4v3L1.8 10.5h10.4L11 8.5v-3a4 4 0 00-4-4zM5.5 12a1.5 1.5 0 003 0" fill="none" stroke="#e5484d" strokeWidth="1.4" /></svg>
          {ov?.alerts?.HIGH > 0 && <span className="badge-dot" />}
        </button>
        {health && health.data_mode === "local" && <span className="mode-pill">Local preview data · Genie off</span>}
        {health && health.data_mode === "databricks" && !health.genie_configured && <span className="mode-pill">Genie space not configured</span>}
        {open === "search" && <SearchBox onClose={() => setOpen(null)} />}
        {open === "alerts" && <AlertsBox ov={ov} onClose={() => setOpen(null)} />}
      </div>
    </>
  );
}

function useApiLite(path) {
  const [data, setData] = useState(null);
  useEffect(() => {
    get(path).then(setData).catch(() => {});
  }, [path]);
  return { data };
}

function SearchBox({ onClose }) {
  const { nav, openLibrary } = useApp();
  const [text, setText] = useState("");
  const [clients, setClients] = useState([]);
  const [questions, setQuestions] = useState([]);
  useEffect(() => {
    get("/api/answers").then(setQuestions).catch(() => {});
  }, []);
  useEffect(() => {
    const t = setTimeout(() => {
      if (text.length < 2) return setClients([]);
      get(`/api/clients?search=${encodeURIComponent(text)}&limit=6`).then((d) => setClients(d.clients)).catch(() => {});
    }, 200);
    return () => clearTimeout(t);
  }, [text]);
  const qs = text.length > 1 ? questions.filter((q) => q.question.toLowerCase().includes(text.toLowerCase())).slice(0, 5) : [];
  return (
    <div className="dropdown" onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <input autoFocus placeholder="Search clients or the 30 certified questions…" value={text} onChange={(e) => setText(e.target.value)} />
      {clients.length > 0 && <div className="grp">Clients</div>}
      {clients.map((c) => (
        <div key={c.client_id} className="item" onClick={() => { onClose(); nav("clients", { step: "profile", client: c.client_id }); }}>
          <span>{c.client_name}</span>
          <span className="muted small">{c.client_id}</span>
        </div>
      ))}
      {qs.length > 0 && <div className="grp">Certified questions</div>}
      {qs.map((q) => (
        <div key={q.question_id} className="item" onClick={() => { onClose(); openLibrary(q.question_id); }}>
          <span>{q.question}</span>
          <span className="muted small">{q.question_id}</span>
        </div>
      ))}
      {text.length > 1 && (
        <div className="item" onClick={() => { onClose(); nav("portfolio", { q: text, t: Date.now() }); }}>
          <span>Ask Genie: “{text}”</span>
        </div>
      )}
    </div>
  );
}

function AlertsBox({ ov, onClose }) {
  const { nav } = useApp();
  const a = ov?.alerts || {};
  return (
    <div className="dropdown" style={{ left: 40 }}>
      <div className="grp">Early-warning alerts</div>
      <div className="item" onClick={() => { onClose(); nav("early-warning"); }}>
        <span>High priority clients</span><b>{a.HIGH ?? "–"}</b>
      </div>
      <div className="item" onClick={() => { onClose(); nav("early-warning"); }}>
        <span>Requiring review (medium)</span><b>{a.MEDIUM ?? "–"}</b>
      </div>
      <div className="grp">Data quality</div>
      <div className="item" onClick={() => { onClose(); nav("briefing"); }}>
        <span>Projects with open data-quality issues</span><b>{ov?.kpis?.projects_needing_review ?? "–"}</b>
      </div>
    </div>
  );
}
