import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle, Bot, ImagePlus, Loader2, Megaphone, Play, RefreshCw, Sparkles, Star, Target, X,
} from "lucide-react";
import { api } from "../api.js";
import AssetCard from "./AssetCard.jsx";
import ExportPanel from "./ExportPanel.jsx";
import RunProgress from "./RunProgress.jsx";
import "../phase4.css";

const LIVE = ["queued", "running"];

function download(filename, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// Step 7 + 10: the planner's asset list; while a run is paused the user can edit it before anything is generated.
function PlanReview({ ws, catalog, run, onApprove, onCancel, busy }) {
  const [picked, setPicked] = useState(() => ws.items.map((i) => i.key));
  const toggle = (k) => setPicked((p) => (p.includes(k) ? p.filter((x) => x !== k) : [...p, k]));
  const max = catalog?.max_assets || 6;
  return (
    <section className="card ag-review">
      <h3><Play size={17} /> Review the plan, then let the agent generate</h3>
      <p className="muted">{ws.plan?.summary} Untick anything you do not need, or add more from the list. Nothing has been generated yet, so no image credits were used.</p>
      <div className="ag-pick">
        {(catalog?.assets || []).map((a) => {
          const planned = ws.items.find((i) => i.key === a.key);
          return (
            <label key={a.key} className={`ag-pick-item ${picked.includes(a.key) ? "on" : ""}`}>
              <input type="checkbox" checked={picked.includes(a.key)} onChange={() => toggle(a.key)} />
              <span>
                <strong>{a.label}</strong>
                <small>{planned?.reason || a.description}</small>
              </span>
              {planned && <span className="pill">Planned</span>}
            </label>
          );
        })}
      </div>
      <div className="ag-review-actions">
        <button className="btn ghost" onClick={onCancel} disabled={busy}><X size={14} /> Cancel run</button>
        <button className="btn primary" disabled={busy || !picked.length || picked.length > max} onClick={() => onApprove(picked)}>
          {busy ? <Loader2 size={15} className="spin" /> : <Play size={15} />} Approve plan &amp; generate {picked.length} {picked.length === 1 ? "asset" : "assets"}
        </button>
      </div>
      {picked.length > max && <small className="err"><AlertTriangle size={13} /> Choose at most {max} assets.</small>}
    </section>
  );
}

export default function AgentWorkspace({ runId, campaignId, onNew, onOpenStudio, onError }) {
  const [run, setRun] = useState(null);
  const [ws, setWs] = useState(null);
  const [cid, setCid] = useState(campaignId || null);
  const [catalog, setCatalog] = useState(null);
  const [working, setWorking] = useState(false);     // a request (not a run) is in flight
  const [cascade, setCascade] = useState(false);

  const live = !!run && LIVE.includes(run.status);
  const paused = run?.status === "awaiting_approval";

  // opened from the history: load the saved campaign (and any run that is still active)
  useEffect(() => {
    if (!campaignId) return;
    api.agentWorkspace(campaignId)
      .then((w) => { setWs(w); setRun(w.active_run || w.last_run || null); })
      .catch((e) => onError(e.message));
  }, [campaignId, onError]);

  // started from the brief: watch the new run
  useEffect(() => {
    if (!runId) return;
    api.agentGetRun(runId).then(setRun).catch((e) => onError(e.message));
  }, [runId, onError]);

  useEffect(() => { api.agentAssets().then(setCatalog).catch(() => {}); }, []);

  // polling: progress timeline + assets appearing one by one while the run is active
  useEffect(() => {
    if (!run || !LIVE.includes(run.status)) return undefined;
    let stop = false;
    const tick = async () => {
      try {
        const r = await api.agentGetRun(run.id);
        if (stop) return;
        setRun(r);
        if (r.campaign_id) {
          setCid(r.campaign_id);
          const w = await api.agentWorkspace(r.campaign_id);
          if (!stop) setWs(w);
        }
      } catch (e) { if (!stop) onError(e.message); }
    };
    const t = setInterval(tick, 1500);
    tick();
    return () => { stop = true; clearInterval(t); };
  }, [run?.id, run?.status, onError]); // eslint-disable-line react-hooks/exhaustive-deps

  // when a run pauses for approval, the plan only exists in the workspace: fetch it once
  useEffect(() => {
    if (paused && run.campaign_id) api.agentWorkspace(run.campaign_id).then((w) => { setCid(run.campaign_id); setWs(w); }).catch(() => {});
  }, [paused, run?.campaign_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const labels = useMemo(() => Object.fromEntries((ws?.items || []).map((i) => [i.key, i.label])), [ws]);

  const startRun = async (fn) => {
    onError("");
    try { setRun(await fn()); } catch (e) { onError(e.message); }
  };
  const regen = (body) => startRun(() => api.agentRegenerate(cid, body));
  const approve = async (key, status) => {
    onError("");
    try { setWs(await api.agentApprovals(cid, { [key]: status })); } catch (e) { onError(e.message); }
  };
  const doExport = async (format) => {
    setWorking(true); onError("");
    try {
      const r = await api.agentExport(cid, { confirm: true, format });
      download(r.filename, r.content, format === "json" ? "application/json" : "text/markdown");
    } catch (e) { onError(e.message); }
    setWorking(false);
  };
  const openStudio = async (view) => { try { await onOpenStudio(view, cid); } catch (e) { onError(e.message); } };

  const s = ws?.strategy?.data;
  const c = ws?.campaign;
  const items = ws?.items || [];
  const locked = live || paused;

  if (!run && !ws) return <div className="card empty"><Loader2 className="spin" size={28} /> Loading campaign…</div>;

  return (
    <div className="ag">
      {run && (
        <RunProgress
          run={run}
          labels={labels}
          onBack={onNew}
          onCancel={() => startRun(() => api.agentCancel(run.id))}
        />
      )}

      {paused && ws && (
        <PlanReview
          key={run.id}
          ws={ws}
          catalog={catalog}
          run={run}
          busy={working}
          onCancel={() => startRun(() => api.agentCancel(run.id))}
          onApprove={async (keys) => {
            setWorking(true);
            await startRun(() => api.agentContinue(run.id, keys));
            setWorking(false);
          }}
        />
      )}

      {c && (
        <>
          <div className="cs-top">
            <div className="meta">
              <span className="pill">{c.product_name}</span><span className="pill">{c.platform}</span>
              <span className="pill dim">{c.objective}</span><span className="pill dim">{c.tone}</span><span className="pill dim">{c.language}</span>
            </div>
            <div className="actions">
              <button className="btn sm ghost" onClick={() => openStudio("content")}><Megaphone size={14} /> Content Studio</button>
              <button className="btn sm ghost" onClick={() => openStudio("creative")}><ImagePlus size={14} /> Visual Studio</button>
              <button className="btn sm" onClick={onNew}><Bot size={14} /> New campaign</button>
            </div>
          </div>

          {c.stale && (
            <div className="banner warn">
              <AlertTriangle size={16} />
              <span>The strategy was regenerated after this copy and these images were created. Regenerate the assets (or the complete campaign) so they match the new strategy.</span>
            </div>
          )}

          {s && (
            <section className="card ag-strategy">
              <div className="ag-strategy-main">
                <span className="vc-eyebrow">Strategy · via {ws.strategy.provider}{ws.strategy.model !== ws.strategy.provider ? ` · ${ws.strategy.model}` : ""}</span>
                <h3>{s.campaign_idea.title}</h3>
                <p className="hook-q">“{s.campaign_idea.hook}”</p>
                <p className="muted">{s.campaign_idea.concept}</p>
                <div className="tags">
                  {s.key_selling_points.slice(0, 4).map((k, i) => <span className="tag" key={i}><Star size={11} /> {k.point}</span>)}
                </div>
                <div className="ag-aud"><Target size={14} /> {s.target_audience.summary}</div>
              </div>
              <div className="ag-strategy-actions">
                <button className="btn sm" disabled={locked} onClick={() => regen({ scope: "strategy", cascade })}>
                  <RefreshCw size={14} /> Regenerate strategy only
                </button>
                <label className="check"><input type="checkbox" checked={cascade} onChange={(e) => setCascade(e.target.checked)} /> also rewrite copy &amp; images</label>
                <button
                  className="btn sm ghost" disabled={locked}
                  onClick={() => confirm("Regenerate the strategy, all copy and all images for this campaign? Existing versions are replaced.") && regen({ scope: "campaign" })}
                >
                  <Sparkles size={14} /> Regenerate complete campaign
                </button>
              </div>
            </section>
          )}

          {ws.plan && (
            <div className="ag-plan">
              <p className="muted"><Bot size={14} /> <b>Campaign plan</b> ({ws.plan.source === "ai" ? "AI planner" : ws.plan.source === "user" ? "chosen by you" : "rule-based"}): {ws.plan.summary}</p>
            </div>
          )}

          {!ws.plan && !locked && (
            <section className="card empty">
              <Bot size={30} />
              <h3>This campaign has no asset plan yet</h3>
              <p className="muted">It was created with the step-by-step tools. Let the agent plan the assets and generate them from the existing strategy.</p>
              <button className="btn primary" onClick={() => regen({ scope: "plan" })}><Play size={15} /> Plan and generate assets</button>
            </section>
          )}

          {items.length > 0 && (
            <>
              <div className="ag-grid">
                {items.map((it) => (
                  <AssetCard
                    key={it.key}
                    item={it}
                    busy={live && (run.items || []).includes(it.key)}
                    locked={locked}
                    onApprove={(st) => approve(it.key, st)}
                    onCaption={() => regen({ scope: "caption", target: it.key })}
                    onImage={() => regen({ scope: "image", target: it.key })}
                  />
                ))}
              </div>
              <ExportPanel approved={ws.approved_count} total={items.length} busy={working || locked} onExport={doExport} />
            </>
          )}
        </>
      )}
    </div>
  );
}
