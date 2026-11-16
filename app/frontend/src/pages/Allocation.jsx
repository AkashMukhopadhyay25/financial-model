import React, { useState } from "react";
import { createPortal } from "react-dom";
import { flagReview, post } from "../api.js";
import { useApp } from "../App.jsx";
import { RichText } from "../Genie.jsx";
import { int, musd, pct, title } from "../format.js";
import { DataTable, ErrorBox, Info, Tag, Toast, useApi } from "../ui.jsx";
import { LEVEL, PastRuns, Steps } from "./Stress.jsx";

// Capital Allocation Agent: the second of the team's own agents (same core as the stress test).
// Code applies the A23 ranking rule and attaches the cited market research (A24); the model explains and connects them.
const STANCE = { prioritise: "green", neutral: "grey", caution: "amber" };

export default function Allocation() {
  const { openAssumptions } = useApp();
  const info = useApi("/api/agents/capital-allocation");
  const [text, setText] = useState("");
  const [turns, setTurns] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);

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
      const r = await post("/api/agents/capital-allocation/ask", { question: qtext, history });
      setTurns((ts) => [...ts, { question: qtext, result: r }]);
      setText("");
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head" style={{ marginTop: 4 }}>
        <div>
          <h1 className="title">Capital allocation</h1>
          <div className="subtitle">
            Where to put new commitments, and where to be careful: our track record beside cited market research.
          </div>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => openAssumptions(["A09", "A11", "A15", "A23", "A24"])}>Assumptions</button>
          <button className="btn" onClick={() => setHistoryOpen(true)}>Past runs</button>
          {turns.length > 0 && <button className="btn" onClick={() => setTurns([])}>New conversation</button>}
        </div>
      </div>

      <div className="ask">
        <div className="ask-head">
          <span>
            <b>{info.data?.title || "Capital Allocation Agent"}</b>
            {info.data?.model && <span className="muted"> · model {info.data.model}</span>}
          </span>
          <Info text="Code ranks industries and regions on four credit metrics from the certified portfolio (A23) and applies the decision rule; the curated, dated research (A24) sits beside it, never blended in. The agent explains the result, cites every source as [S#] and checks the four-client recommendation. The app verifies every figure in its answer and that it never prioritises a concentration-flagged region." />
        </div>
        <div className="ask-row">
          <input
            value={text}
            placeholder={turns.length ? "Ask a follow-up, e.g. 'which Energy clients outside Africa could we grow with?'" : "e.g. Which industry should we prioritise for new commitments?"}
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
            {(info.data?.presets || []).map((p) => (
              <button key={p} className="chip plain" title={p} onClick={() => ask(p)} disabled={busy}>{p}</button>
            ))}
          </div>
        )}
      </div>

      {err && <div className="mt"><ErrorBox error={err} /></div>}
      {busy && (
        <div className="card mt small muted">
          The agent is ranking segments on the certified tables and reading the curated research (usually 10–20 seconds)…
        </div>
      )}
      {[...turns].reverse().map((t, i) => <Turn key={turns.length - i} question={t.question} r={t.result} />)}
      {!turns.length && !busy && <Intro />}
      {historyOpen && (
        <PastRuns agent="capital-allocation" label="capital-allocation" onClose={() => setHistoryOpen(false)}
          onOpen={(r) => { setTurns((ts) => [...ts, { question: r.question, result: r }]); setHistoryOpen(false); }} />
      )}
    </>
  );
}

function pick(r, tool, test = () => true) {
  return (r.results || []).filter((x) => x.tool === tool && test(x.result)).map((x) => x.result).pop();
}

function Turn({ question, r }) {
  const [steps, setSteps] = useState(false);
  const [toast, setToast] = useState(null);
  const lvl = LEVEL[r.trust?.level] || LEVEL.HUMAN_REVIEW_REQUIRED;
  const sum = pick(r, "get_allocation_summary");
  const ind = pick(r, "rank_segments", (x) => x.dimension === "industry");
  const reg = pick(r, "rank_segments", (x) => x.dimension === "region");
  const outlook = pick(r, "get_market_outlook", (x) => (x.rows || []).length > 3);
  const recs = pick(r, "get_board_recommendations");
  const cited = new Set((r.answer || "").match(/S\d+/g) || []);

  const escalate = async () => {
    await flagReview({
      entity_type: "answer", entity_id: r.run_id || "capital-allocation", entity_name: question.slice(0, 200),
      action: "flag_for_review", source_page: "capital-allocation",
      note: `Capital-allocation view sent to the Credit Risk Committee. Trust: ${r.trust?.level}. ${sum ? `Prioritise ${sum.prioritise_industry}; caution ${sum.caution_industry}; limit ${sum.regions_to_limit.join(", ")}.` : ""}`,
    });
    setToast("Sent to the Credit Risk Committee review queue");
  };

  return (
    <div className="card mt">
      <div className="card-head">
        <div>
          <div className="small muted">You asked</div>
          <h3 style={{ marginTop: 2 }}>{question}</h3>
        </div>
        <Tag color={lvl.color}>{lvl.label}</Tag>
      </div>

      {sum && (
        <div className="grid g2" style={{ gridTemplateColumns: "repeat(4, minmax(0, 1fr))" }}>
          <Tile label="Prioritise" value={sum.prioritise_industry} tone="green"
                foot={`Rank ${sum.prioritise_industry_rank} · market ${sum.data_and_market_agree[sum.prioritise_industry] ? "agrees" : "differs"}`} />
          <Tile label="Approach with caution" value={sum.caution_industry} tone="amber"
                foot={`Rank ${sum.caution_industry_rank} · market ${sum.data_and_market_agree[sum.caution_industry] ? "agrees" : "differs"}`} />
          <Tile label="Grow in" value={sum.regions_to_grow.join(" · ")} small foot="Best-ranked regions, not concentrated" />
          <Tile label="Limit new exposure" value={sum.regions_to_limit.join(" · ")} tone="red" small
                foot={`Concentration limit ${pct(sum.concentration_limit)} of current exposure`} />
        </div>
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

      <div className="grid g2 mt">
        {ind && <Ranking title="Industries (A23)" dim="industry" rows={ind.rows} />}
        {reg && <Ranking title="Regions (A23)" dim="region" rows={reg.rows} />}
      </div>

      {recs && (
        <div className="mt">
          <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>The four-client recommendation against this view</div>
          <DataTable
            rows={recs.rows}
            columns={[
              { key: "recommendation", label: "Recommendation", render: (v) => <Tag color={v === "CONTINUE" ? "green" : "red"}>{v === "CONTINUE" ? "Continue" : "Reduce / review"}</Tag> },
              { key: "client_name", label: "Client", strong: true },
              { key: "primary_industry", label: "Industry" },
              { key: "industry_rank", label: "Industry rank" },
              { key: "primary_region", label: "Region" },
              { key: "region_rank", label: "Region rank" },
              { key: "region_concentration_flag", label: "Concentrated", render: (v) => (v ? <Tag color="red">yes</Tag> : "no") },
              { key: "exposure_affected_musd", label: "Exposure affected", num: true, render: (v) => musd(v) },
            ]}
          />
        </div>
      )}

      {outlook && (
        <div className="mt">
          <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>
            Market research (A24) · curated, cited and dated · retrieved {outlook.rows[0]?.retrieved_date}
          </div>
          <div className="grid g2">
            {outlook.rows.map((o) => (
              <div key={o.source_id} className="card" style={{ boxShadow: "none", borderColor: cited.has(o.source_id) ? "var(--blue)" : undefined }}>
                <div className="kpi-label">
                  <span><b>[{o.source_id}]</b> {o.publisher} · {o.published_date}</span>
                  <span style={{ display: "flex", gap: 6 }}>
                    {cited.has(o.source_id) && <Tag color="blue">cited</Tag>}
                    <Tag color={STANCE[o.stance] || "grey"}>{o.stance}</Tag>
                  </span>
                </div>
                <div className="small" style={{ margin: "6px 0" }}>
                  <a href={o.url} target="_blank" rel="noreferrer">{o.title}</a>
                  <span className="muted"> · {o.industry === "ALL" ? "all industries" : o.industry}{o.region !== "ALL" ? ` · ${o.region}` : ""}</span>
                </div>
                <div className="small muted">{o.finding}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt" style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <button className="btn small" onClick={() => setSteps(true)}>How the agent worked ({(r.trace || []).length} steps)</button>
        <button className="btn small" onClick={escalate}>Send to Credit Risk Committee</button>
        <span className="small muted">
          {r.model} · {(r.latency_ms / 1000).toFixed(1)} s{r.run_id ? ` · logged as ${r.run_id.slice(0, 8)} in ops_agent_runs` : ""}
        </span>
      </div>
      {steps && createPortal(<Steps r={r} onClose={() => setSteps(false)} />, document.body)}
      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
    </div>
  );
}

function Tile({ label, value, foot, tone, small }) {
  return (
    <div className="card" style={{ boxShadow: "none" }}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value ${tone === "red" ? "red" : tone === "amber" ? "amber" : ""}`}
           style={{ fontSize: small ? 20 : 30, color: tone === "green" ? "var(--green)" : undefined }}>{value}</div>
      <div className="kpi-foot">{foot}</div>
    </div>
  );
}

function Ranking({ title: t, dim, rows }) {
  return (
    <div>
      <div className="small" style={{ fontWeight: 600, marginBottom: 6 }}>{t}</div>
      <DataTable
        rows={rows}
        columns={[
          { key: "overall_rank", label: "Rank", num: true },
          { key: dim, label: title(dim), strong: true, render: (v, row) => <>{v} {row.concentration_flag && <Tag color="red">concentrated</Tag>}</> },
          { key: "portfolio_share", label: "Share", num: true, render: (v) => pct(v, 1) },
          { key: "distressed_share", label: "Distressed", num: true, render: (v) => pct(v, 1) },
          { key: "ecl_rate", label: "ECL rate", num: true, render: (v) => pct(v, 1) },
          { key: "closed_loss_rate", label: "Closed loss", num: true, render: (v) => pct(v, 1) },
          { key: "weighted_risk_rating", label: "Rating", num: true },
        ]}
      />
    </div>
  );
}

function Intro() {
  return (
    <div className="grid g3 mt">
      <div className="card">
        <h3>1 · Our track record (A23)</h3>
        <p className="small muted">
          Code ranks industries and regions on four credit metrics from the certified portfolio: distressed share, ECL rate,
          losses on closed projects and risk rating. It flags any region holding more than 25% of current exposure.
        </p>
      </div>
      <div className="card">
        <h3>2 · The market view (A24)</h3>
        <p className="small muted">
          Curated outlooks from the IMF, World Bank, IEA, GSMA, WTO and FAO, each cited and dated. They sit beside the
          ranking, never blended into it, so you can see where the data and the market agree.
        </p>
      </div>
      <div className="card">
        <h3>3 · A recommendation you can check</h3>
        <p className="small muted">
          The agent explains the view, tests the four-client recommendation against it and cites every source. The app checks
          every figure and blocks advice that would deepen a concentration. One click sends it to the Credit Risk Committee.
        </p>
      </div>
    </div>
  );
}
