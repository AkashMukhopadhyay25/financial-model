import React from "react";
import { useApp } from "../App.jsx";
import Allocation from "./Allocation.jsx";
import Stress from "./Stress.jsx";

// WS3 decision support: the team's own agents (alongside Genie) under one tab. Both stay mounted, so switching
// between them keeps each conversation.
const AGENTS = [
  { id: "stress", label: "Reserve & stress test", hint: "What if credit conditions get worse?" },
  { id: "allocation", label: "Capital allocation", hint: "Where should new money go?" },
];

export default function Agents({ params }) {
  const { nav } = useApp();
  const active = AGENTS.some((a) => a.id === params.agent) ? params.agent : "stress";
  return (
    <>
      <div className="eyebrow blue">WS3 · Decision support · Our agents alongside Genie</div>
      <div className="seg" style={{ marginTop: 8 }} role="tablist" aria-label="Agents">
        {AGENTS.map((a) => (
          <button key={a.id} role="tab" aria-selected={active === a.id} title={a.hint}
                  className={active === a.id ? "active" : ""} onClick={() => nav("agents", { agent: a.id })}>
            {a.label}
          </button>
        ))}
      </div>
      <div style={{ display: active === "stress" ? "block" : "none" }}><Stress /></div>
      <div style={{ display: active === "allocation" ? "block" : "none" }}><Allocation /></div>
    </>
  );
}
