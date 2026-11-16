import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { flagReview, get, post } from "../api.js";
import { useApp } from "../App.jsx";
import { RichText } from "../Genie.jsx";
import { dateTime, int, musd, pct, title } from "../format.js";
import { DataTable, Drawer, ErrorBox, Flow, Info, SqlBlock, Tag, Toast, useApi } from "../ui.jsx";

// Reserve & Stress-Test Agent: the team's own agent alongside Genie. The model picks the scenario and explains it;
// deterministic SQL on the certified tables computes every figure, and the app checks every figure in the answer.
export const LEVEL = {
  VALIDATED: { label: "Green · Validated", color: "green" },
  REVIEW_RECOMMENDED: { label: "Amber · Review recommended", color: "amber" },
  HUMAN_REVIEW_REQUIRED: { label: "Red · Human review required", color: "red" },
};

export default function Stress({ embedded = false, pending = null }) {
  const { openAssumptions } = useApp();
  const info = useApi("/api/agents/stress-test");
  const [text, setText] = useState("");
  const [turns, setTurns] = useState([]); // [{question, result}]
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const lastPending = useRef(null);

  const ask = async (question) => {
    const qtext = (question || text).trim();
    if (!qtext || busy) return;
    setBusy(true);
    setErr(null);
    const history = turns.slice(-3).flatMap((t) => [
      { role: "user", content: t.question },
      { role: "assistant", content: t.result.answer || "" },
    ]);
    try {
      const r = await post("/api/agents/stress-test/ask", { question: qtext, history });
      setTurns((ts) => [...ts, { question: qtext, result: r }]);
      setText("");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  const presets = info.data?.presets || [];
  useEffect(() => {
    if (pending && pending.id !== lastPending.current) {
      lastPending.current = pending.id;
      ask(pending.q);
    }
  }); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="page-head" style={{ marginTop: 4 }}>
        <div>
          {embedded ? <h2 className="title" style={{ fontSize: 28, margin: 0 }}>Reserve &amp; stress test</h2> : <h1 className="title">Reserve &amp; stress test</h1>}
          <div className="subtitle">
            Ask a what-if in plain language. The agent chooses the scenario; certified SQL computes every figure.
          </div>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => openAssumptions(["A09", "A10", "A11"])}>Assumptions</button>
          <button className="btn" onClick={() => setHistoryOpen(true)}>Past runs</button>
          {turns.length > 0 && <button className="btn" onClick={() => setTurns([])}>New conversation</button>}
        </div>
      </div>

      <div className="ask">
        <div className="ask-head">
          <span>
            <b>{info.data?.title || "Reserve & Stress-Test Agent"}</b>
          </span>
          <Info text="Genie answers 'what happened?'. This agent answers 'what if?': it turns your question into one or more scenarios, runs them with governed SQL on certified_investment_portfolio, and explains the result. It never computes a number itself; the app checks that every figure in its answer comes from a tool result." />
        </div>
        <div className="ask-row">
          <input
            value={text}
            placeholder={turns.length ? "Ask a follow-up, e.g. 'and at a 75% loss rate?'" : "e.g. What if Watchlist projects in Latin America default?"}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
            disabled={busy}
          />
          <button className="btn dark" onClick={() => ask()} disabled={busy || !text.trim()}>
            {busy ? "Running…" : "Run"}
          </button>
        </div>
        {!turns.length && (
          <div className="chips">
            <span className="chip-label">Try:</span>
            {presets.map((p) => (
              <button key={p} className="chip plain" title={p} onClick={() => ask(p)} disabled={busy}>{p}</button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="mt"><ErrorBox error={err} /></div>}
      {busy && (
        <div className="card mt small muted">
          The agent is choosing scenarios and running them on the certified tables (usually 5–15 seconds)…
        </div>
      )}
      {[...turns].reverse().map((t, i) => (
        <Turn key={turns.length - i} question={t.question} r={t.result} latest={i === 0} />
      ))}
      {!turns.length && !busy && <HowItWorks />}
      {historyOpen && <PastRuns onClose={() => setHistoryOpen(false)} onOpen={(r) => { setTurns((ts) => [...ts, { question: r.question, result: r }]); setHistoryOpen(false); }} />}
    </>
  );
}

function Turn({ question, r, latest }) {
  const { openProject } = useApp();
  const [pick, setPick] = useState(0);
  const [sql, setSql] = useState(false);
  const [toast, setToast] = useState(null);
  const [sent, setSent] = useState(false);
  const lvl = LEVEL[r.trust?.level] || LEVEL.HUMAN_REVIEW_REQUIRED;
  const scenarios = (r.results || []).filter((x) => x.tool === "run_stress_scenario").map((x) => x.result);
  const s = scenarios[Math.min(pick, scenarios.length - 1)];
  const baselines = (r.results || []).filter((x) => x.tool === "get_risk_baseline").map((x) => x.result);

  const escalate = async () => {
    if (sent) return;
    setSent(true);
    await flagReview({
      entity_type: "answer", entity_id: r.run_id || "stress-test", entity_name: question.slice(0, 200),
      action: "flag_for_review", source_page: "stress-test",
      note: `Stress-test result sent to the Credit Risk Committee. Trust: ${r.trust?.level}. ${s ? `Stressed ECL ${musd(s.summary.ecl_stressed_musd)} (+${musd(s.summary.ecl_increase_musd)}).` : ""}`,
    });
    setToast("Sent to the Credit Risk Committee review queue");
  };

  return (
    <div className="card mt" style={latest ? {} : { opacity: 0.92 }}>
      <div className="card-head">
        <div>
          <div className="small muted">You asked</div>
          <h3 style={{ marginTop: 2 }}>{question}</h3>
        </div>
        <Tag color={lvl.color}>{lvl.label}</Tag>
      </div>

      {s && (
        <>
          {scenarios.length > 1 && (
            <div className="chips" style={{ marginTop: 0, marginBottom: 12 }}>
              <span className="chip-label">Scenarios run:</span>
              {scenarios.map((x, i) => (
                <button key={i} className={`chip ${i === pick ? "" : "plain"}`} onClick={() => setPick(i)}>{x.name}</button>
              ))}
            </div>
          )}
          <div className="grid g3">
            <Kpi label="Baseline expected credit loss" value={musd(s.summary.ecl_baseline_musd)}
                 foot={`${int(s.summary.past_due_projects)} Past Due projects · A11`} />
            <Kpi label="Stressed expected credit loss" value={musd(s.summary.ecl_stressed_musd)} tone="red"
                 foot={s.name} />
            <Kpi label="Additional reserve needed" value={`+${musd(s.summary.ecl_increase_musd)}`} tone="amber"
                 foot={`${musd(s.summary.ecl_increase_from_shocked_projects_musd)} newly defaulted · ${musd(s.summary.ecl_increase_from_existing_past_due_musd)} existing Past Due`} />
          </div>
          <div className="small muted mt">
            Shocked: {int(s.summary.shocked_projects)} projects ({int(s.summary.shocked_watchlist_projects)} Watchlist,{" "}
            {int(s.summary.shocked_performing_projects)} Performing) of {int(s.summary.shocked_clients)} clients ·{" "}
            {musd(s.summary.shocked_exposure_musd)} disbursed + {musd(s.summary.shocked_undisbursed_musd)} undisbursed at risk ·
            {" "}{int(s.summary.shocked_projects_with_dq_issues)} with open data-quality issues (included)
          </div>
        </>
      )}

      {r.answer && (
        <div className="mt">
          <div className="small" style={{ fontWeight: 600, marginBottom: 4 }}>Agent's explanation</div>
          <RichText text={r.answer} />
        </div>
      )}
      {r.error && <div className="mt"><ErrorBox error={{ message: r.error }} /></div>}

      <div className={`trust ${r.trust?.color || "red"}`}>
        <b>{lvl.label}</b>
        <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
          {(r.trust?.reasons || []).map((x, i) => <li key={i}>{x}</li>)}
        </ul>
      </div>

      {s && (
        <div className="grid g2 mt">
          <div>
            <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Where the increase comes from (by {title(s.parameters.group_by)})</div>
            <DataTable
              rows={s.breakdown}
              columns={[
                { key: s.parameters.group_by, label: title(s.parameters.group_by), strong: true },
                { key: "shocked_projects", label: "Shocked", num: true },
                { key: "ecl_stressed_musd", label: "Stressed ECL", num: true, render: (v) => musd(v) },
                { key: "ecl_increase_musd", label: "Increase", num: true, render: (v) => `+${musd(v)}` },
              ]}
            />
          </div>
          <div>
            <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Projects contributing most</div>
            <DataTable
              rows={s.top_projects}
              onRowClick={(row) => openProject(row.project_url)}
              columns={[
                { key: "project_name", label: "Project", strong: true },
                { key: "client_name", label: "Client" },
                { key: "performance_status", label: "Today" },
                { key: "ecl_stressed_musd", label: "Stressed ECL", num: true, render: (v) => musd(v) },
              ]}
            />
          </div>
        </div>
      )}
      {!s && baselines.map((b, i) => (
        <div className="mt" key={i}>
          <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>Risk today by {title(b.group_by)}</div>
          <DataTable rows={b.rows} />
        </div>
      ))}

      {s && (
        <div className="mt small">
          <b>Scenario assumptions</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{s.assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </div>
      )}

      <div className="mt" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button className="btn small" onClick={() => setSql(true)}>How the agent worked ({(r.trace || []).length} steps)</button>
        <button className="btn small" onClick={escalate} disabled={sent}>{sent ? "Sent to Credit Risk Committee ✓" : "Send to Credit Risk Committee"}</button>
        <span className="small muted">
          {r.model} · {(r.latency_ms / 1000).toFixed(1)} s{r.run_id ? ` · logged as ${r.run_id.slice(0, 8)} in ops_agent_runs` : ""}
        </span>
      </div>
      {sql && createPortal(<Steps r={r} onClose={() => setSql(false)} />, document.body)}
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
    </div>
  );
}

function Kpi({ label, value, foot, tone }) {
  return (
    <div className="card" style={{ boxShadow: "none" }}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone || ""}`} style={{ fontSize: 34 }}>{value}</div>
      <div className="kpi-foot">{foot}</div>
    </div>
  );
}

export function Steps({ r, onClose }) {
  return (
    <Drawer title="How the agent worked" onClose={onClose}>
      <p className="small muted" style={{ marginTop: 0 }}>
        Each step is a governed tool call: the model chose the tool and its parameters; the SQL below ran on the
        certified tables and produced every figure. The app then checked each figure in the answer against these results.
      </p>
      {(r.trace || []).map((t, i) => (
        <div key={i} style={{ marginBottom: 18 }}>
          <div className="small" style={{ fontWeight: 600 }}>
            {i + 1}. {t.tool}{" "}
            {t.error ? <Tag color="red">error</Tag> : <Tag color="green">{int(t.rows)} rows</Tag>}
          </div>
          <pre className="code" style={{ margin: "6px 0" }}>{JSON.stringify(t.arguments, null, 2)}</pre>
          {t.error && <div className="small" style={{ color: "var(--red)" }}>{t.error}</div>}
          {t.sql && <SqlBlock sql={t.sql} comment="SQL run on the certified tables" />}
        </div>
      ))}
      {(r.trust?.untraced_figures || []).length > 0 && (
        <p className="small">Figures not found in any tool result: {r.trust.untraced_figures.join(", ")}</p>
      )}
    </Drawer>
  );
}

export function PastRuns({ onClose, onOpen, agent = "stress-test", label = "stress-test" }) {
  const { data, error, loading } = useApi(`/api/agents/${agent}/runs`);
  return (
    <Drawer title={`Past ${label} runs`} onClose={onClose}>
      {error && <ErrorBox error={error} />}
      {loading && <div className="small muted">Loading…</div>}
      {data && !data.length && <div className="small muted">No runs yet.</div>}
      {(data || []).map((h) => (
        <div key={h.run_id} className="card" style={{ marginBottom: 8, cursor: "pointer", boxShadow: "none" }}
             onClick={() => get(`/api/agents/runs/${h.run_id}`).then(onOpen)}>
          <div className="small muted">{dateTime(h.asked_at)} · {h.asked_by}</div>
          <div style={{ margin: "4px 0" }}>{h.question}</div>
          <Tag color={(LEVEL[h.trust_level] || LEVEL.HUMAN_REVIEW_REQUIRED).color}>
            {(LEVEL[h.trust_level] || LEVEL.HUMAN_REVIEW_REQUIRED).label.split(" · ")[0]}
          </Tag>
        </div>
      ))}
    </Drawer>
  );
}

function HowItWorks() {
  return (
    <Flow title="How the stress-test agent works" steps={[
      { who: "You", title: "Ask a what-if", text: "e.g. \"What if Watchlist projects in Africa default and clients draw half their commitments?\"" },
      { who: "Agent", title: "Turn it into a scenario", text: "The agent picks which projects default (Watchlist, risk rating 5-6, a region, sector or client), the loss rate and any drawdown of undisbursed commitments." },
      { who: "Code", title: "Compute with certified SQL", text: "The stress engine runs the scenario on the certified portfolio: baseline vs stressed expected credit loss (60% loss on defaulted exposure, A11), what drives it, the projects behind it." },
      { who: "Agent", title: "Explain and check", text: "The agent explains the result with the stated assumptions. The app checks every figure against the SQL and sets a trust level (Green / Amber / Red)." },
      { who: "People", title: "The Committee decides", text: "One click sends the result to the Credit Risk Committee's review queue, where the decision is recorded." },
    ]} />
  );
}
