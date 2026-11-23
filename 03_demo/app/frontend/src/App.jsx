import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { get } from "./api.js";
import { ago, date, dateTime, dateTimeFull } from "./format.js";
import { QuestionLibrary } from "./Genie.jsx";
import { ProjectDrawer } from "./Project.jsx";
import { AssumptionsDrawer, Toast } from "./ui.jsx";
import Overview from "./pages/Overview.jsx";
import Portfolio from "./pages/Portfolio.jsx";
import Risk from "./pages/Risk.jsx";
import Clients, { AgentIcon } from "./pages/Clients.jsx";
import EarlyWarning from "./pages/EarlyWarning.jsx";
import Briefing from "./pages/Briefing.jsx";
import Monthly from "./pages/Monthly.jsx";

export const PAGES = [
  { id: "overview", label: "Overview", el: Overview },
  { id: "portfolio", label: "Portfolio analytics", el: Portfolio },
  { id: "risk", label: "Risk & exposure", el: Risk },
  { id: "clients", label: "Client intelligence", el: Clients, menu: [
    { label: "Client recommendations", sub: "Directory, profiles, comparison, Board recommendation", params: { step: "board" }, icon: "clients" },
    { sep: true },
    { label: "Stress-test agent", sub: "Reserve & stress test: what if credit gets worse?", params: { step: "stress" }, agent: "stress" },
    { label: "Capital allocation agent", sub: "Where should new commitments go?", params: { step: "allocation" }, agent: "allocation" },
  ] },
  { id: "early-warning", label: "Early warning", el: EarlyWarning },
  { id: "monthly", label: "Monthly review", el: Monthly },
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
  const [project, setProject] = useState(null); // null | project_url
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
      openProject: (url) => url && setProject(url),
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
      {project && <ProjectDrawer url={project} onClose={() => setProject(null)} onOpen={setProject} />}
      <Toast message={toast} onDone={() => setToast("")} />
    </Ctx.Provider>
  );
}

function Header() {
  const { nav, route, health } = useApp();
  const [open, setOpen] = useState(null); // "search" | "alerts"
  const { data: ov } = useApiLite("/api/overview");
  const refreshed = ov?.data_refreshed_at;
  const [, tick] = useState(0); // re-render every minute so "x min ago" stays current
  useEffect(() => {
    const t = setInterval(() => tick((n) => n + 1), 60000);
    return () => clearInterval(t);
  }, []);
  return (
    <>
      <div className="topbar">
        <div className="brand" onClick={() => nav("overview")}>
          <CloudstruckMark size={32} />
          <span className="wordmark">Cloudstruck</span>
        </div>
        <nav className="nav" aria-label="Pages">
          {PAGES.map((p) =>
            p.menu ? <NavMenu key={p.id} page={p} /> : (
              <button key={p.id} className={route.page === p.id ? "active" : ""} onClick={() => nav(p.id)}>
                {p.label}
              </button>
            ))}
        </nav>
      </div>
      <div className="subbar">
        <span className="pill" title={refreshed ? `Last data load: ${dateTimeFull(refreshed)}. Figures are as of the reporting date ${date(ov?.kpis?.reporting_date)}.` : ""}>
          <span className="dot" /> Data refreshed: {refreshed ? `${dateTime(refreshed)} · ${ago(refreshed)}` : "…"}
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

// A top-bar item with a dropdown (hover or click the caret). The menu is portalled to <body> so the scrolling
// nav bar does not clip it.
function NavMenu({ page }) {
  const { nav, route } = useApp();
  const [rect, setRect] = useState(null);
  const btn = useRef(null);
  const timer = useRef(null);
  const show = () => { clearTimeout(timer.current); setRect(btn.current.getBoundingClientRect()); };
  const hide = () => { timer.current = setTimeout(() => setRect(null), 150); };
  useEffect(() => () => clearTimeout(timer.current), []);
  const go = (params) => { setRect(null); nav(page.id, params); };
  return (
    <span onMouseEnter={show} onMouseLeave={hide} style={{ display: "inline-flex" }}>
      <button ref={btn} className={route.page === page.id ? "active" : ""} aria-haspopup="menu" aria-expanded={!!rect}
              onClick={() => nav(page.id)}>
        {page.label}
        <span aria-label="More" style={{ marginLeft: 6, fontSize: 9, opacity: 0.7 }}
              onClick={(e) => { e.stopPropagation(); rect ? setRect(null) : show(); }}>▼</span>
      </button>
      {rect && createPortal(
        <div className="nav-menu" role="menu" style={{ top: rect.bottom + 6, left: Math.max(8, rect.left) }}
             onMouseEnter={show} onMouseLeave={hide}>
          {page.menu.map((m, i) => m.sep ? <hr key={i} /> : (
            <button key={i} role="menuitem" className={route.page === page.id && route.params.step === m.params.step ? "active" : ""}
                    onClick={() => go(m.params)}>
              {m.agent || m.icon ? <AgentIcon id={m.agent || m.icon} size={16} color="var(--blue)" /> : <span style={{ width: 16 }} />}
              <span><div>{m.label}</div><div className="sub">{m.sub}</div></span>
            </button>
          ))}
        </div>, document.body)}
    </span>
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

// Cloudstruck mark: a lowercase "b" with a single signal arc, on the app's blue gradient (same art as public/favicon.svg).
export function CloudstruckMark({ size = 32 }) {
  // Cloudstruck: a cloud with a lightning strike, on the app's blue gradient tile
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden className="brand-mark">
      <defs>
        <linearGradient id="cs-base" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#5b86f7" />
          <stop offset=".55" stopColor="#2d45c4" />
          <stop offset="1" stopColor="#2f8f9a" />
        </linearGradient>
        <radialGradient id="cs-glow" cx="1" cy="0" r=".75">
          <stop offset="0" stopColor="#ef8a4c" stopOpacity=".95" />
          <stop offset="1" stopColor="#ef8a4c" stopOpacity="0" />
        </radialGradient>
      </defs>
      <rect width="48" height="48" rx="12" fill="url(#cs-base)" />
      <rect width="48" height="48" rx="12" fill="url(#cs-glow)" />
      <path d="M14.6 27a6.4 6.4 0 0 1-.4-12.8 8.8 8.8 0 0 1 17-1.6 6.7 6.7 0 0 1 2 14.4z" fill="#fff" />
      <path d="M26.4 20.5l-7.6 11.6h5.6l-2.8 10.4 10.2-13.6h-6l3.4-8.4z" fill="#ffd27a" stroke="#2d45c4" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
