import { AlertTriangle, Check, ChevronDown, Clock, Loader2, Minus, XCircle } from "lucide-react";

const ICON = {
  done: <Check size={15} />,
  running: <Loader2 size={15} className="spin" />,
  waiting: <Clock size={15} />,
  warning: <AlertTriangle size={15} />,
  failed: <XCircle size={15} />,
  skipped: <Minus size={15} />,
  pending: <span className="dot" />,
};

const HEADLINE = {
  queued: "Starting…",
  running: "The agent is working",
  awaiting_approval: "Waiting for your approval",
  completed: "Run completed",
  completed_with_warnings: "Run completed with warnings",
  failed: "Run failed",
  cancelled: "Run cancelled",
};

const SCOPE = { campaign: "Complete campaign", strategy: "Strategy", caption: "Caption", image: "Image", plan: "Asset plan" };

function Steps({ run }) {
  return (
    <ol className="ag-steps">
      {run.steps.map((s) => (
        <li key={s.key} className={`ag-step ${s.status}`}>
          <span className="ag-step-ico">{ICON[s.status] || ICON.pending}</span>
          <div>
            <strong>{s.label}</strong>
            {s.detail && <small>{s.detail}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

// Steps 4-6 made visible: the image prompts the agent wrote for each asset.
function Prompts({ run, labels }) {
  const keys = Object.keys(run.image_prompts || {});
  if (!keys.length) return null;
  return (
    <details className="ag-prompts">
      <summary><ChevronDown size={14} /> Image prompts written by the agent ({keys.length} {keys.length === 1 ? "asset" : "assets"})</summary>
      {keys.map((k) => (
        <div key={k} className="ag-prompt-group">
          <h5>{labels[k] || k}</h5>
          {run.image_prompts[k].map((p, i) => (
            <div key={i} className="ag-prompt">
              <span className="vc-eyebrow">{p.style_label} · {p.name}</span>
              <p>{p.image_prompt}</p>
            </div>
          ))}
        </div>
      ))}
    </details>
  );
}

export default function RunProgress({ run, labels = {}, onCancel, onBack }) {
  const live = run.status === "queued" || run.status === "running" || run.status === "awaiting_approval";
  const tone = run.status === "failed" ? "bad" : run.status === "completed_with_warnings" ? "warn" : run.status === "completed" ? "good" : "";
  const errors = Object.entries(run.item_errors || {});
  const body = (
    <>
      <Steps run={run} />
      {run.error && <div className="banner" role="alert"><AlertTriangle size={16} /><span>{run.error}</span></div>}
      {run.warnings.map((w) => <div key={w} className="banner warn"><AlertTriangle size={16} /><span>{w}</span></div>)}
      {errors.map(([k, m]) => <div key={k} className="banner warn"><AlertTriangle size={16} /><span>{m}</span></div>)}
      <Prompts run={run} labels={labels} />
    </>
  );
  if (!live && run.status !== "failed") {
    return (
      <details className={`card ag-run ${tone}`}>
        <summary>
          <span className={`ag-dot ${tone}`} /> {HEADLINE[run.status]} <span className="muted">· {SCOPE[run.scope] || run.scope}{run.target ? ` (${labels[run.target] || run.target})` : ""}</span>
        </summary>
        {body}
      </details>
    );
  }
  return (
    <section className={`card ag-run open ${tone}`}>
      <div className="ag-run-head">
        <h3>
          {run.status === "running" || run.status === "queued" ? <Loader2 size={18} className="spin" /> : <span className={`ag-dot ${tone}`} />} {HEADLINE[run.status]}
          <span className="muted"> · {SCOPE[run.scope] || run.scope}{run.target ? ` (${labels[run.target] || run.target})` : ""}</span>
        </h3>
        {(run.status === "running" || run.status === "queued") && onCancel && <button className="btn sm ghost" onClick={onCancel}>Stop after this step</button>}
        {run.status === "failed" && !run.campaign_id && onBack && <button className="btn sm" onClick={onBack}>Back to the brief</button>}
      </div>
      {body}
    </section>
  );
}
