import { useState } from "react";
import {
  Check, CheckCircle2, Download, Maximize2, Loader2, RefreshCw, RotateCcw, Wand2, AlertTriangle, ChevronDown, ChevronUp, X,
} from "lucide-react";

// Step 8: quick instructions for each kind of change (the user can also type anything).
const CATEGORIES = [
  { key: "background", label: "Background", presets: ["Clean white studio backdrop", "Sunlit outdoor scene", "Dark moody gradient", "Soft pastel colour backdrop", "Busy city street at golden hour"] },
  { key: "style", label: "Visual style", presets: ["Flat vector illustration", "Photorealistic photography", "Glossy 3D render", "Watercolour painting", "Retro poster look"] },
  { key: "composition", label: "Composition", presets: ["Product centred with more empty space", "Close-up detail shot", "Product on the left, rule of thirds", "Top-down flat lay", "Wider shot showing the environment"] },
  { key: "tone", label: "Marketing tone", presets: ["More premium and luxurious", "Playful and energetic", "Calm and minimal", "Bold and urgent", "Warm and friendly"] },
];

const NO_RETRY = new Set(["auth", "config", "quota"]);

export default function CreativeCard({ concept, format, spec, selected, busy, onSelect, onOpen, onRevise, onRetry, onUseVersion }) {
  const [panel, setPanel] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  const [cat, setCat] = useState("background");
  const [text, setText] = useState("");
  const img = concept.image;
  const failed = concept.status === "failed";
  const ratio = img ? `${img.width} / ${img.height}` : `${spec.width} / ${spec.height}`;
  const presets = CATEGORIES.find((c) => c.key === cat).presets;

  const apply = async () => {
    const ok = await onRevise(text.trim(), cat);
    if (ok) { setText(""); setPanel(false); }
  };

  return (
    <article className={`card cc ${selected ? "selected" : ""} ${failed ? "failed" : ""}`}>
      <div className="cc-img" style={{ aspectRatio: ratio }}>
        {img && <img src={img.url} alt={concept.name} loading="lazy" onClick={onOpen} />}
        {failed && (
          <div className="cc-fail">
            <AlertTriangle size={22} />
            <strong>Generation failed</strong>
            <p>{concept.error?.message || "The image could not be generated."}</p>
            {concept.error?.retry_after ? <small>Suggested wait: {concept.error.retry_after}s</small> : null}
          </div>
        )}
        {busy && <div className="cc-busy"><Loader2 size={26} className="spin" /><span>Generating…</span></div>}
        {selected && <span className="pill vc-badge cc-badge"><CheckCircle2 size={13} /> Preferred</span>}
        {img && <button className="cc-zoom" title="View larger" onClick={onOpen}><Maximize2 size={15} /></button>}
      </div>

      <div className="cc-body">
        <div>
          <span className="vc-eyebrow">{concept.style_label}</span>
          <h4 className="cc-title">{concept.name}</h4>
          <p className="muted cc-sum">{concept.concept_summary}</p>
        </div>
        {concept.text_overlay && <p className="cc-overlay"><b>Caption idea:</b> {concept.text_overlay}</p>}
        <div className="cc-swatches">
          {concept.color_palette.map((c) => <span key={c} className="tag">{c}</span>)}
        </div>

        {concept.versions.length > 1 && (
          <div className="cc-versions" aria-label="Versions">
            <small>Versions</small>
            {concept.versions.map((v, i) => (
              <button key={v.id} className={v.id === concept.current_version ? "on" : ""} title={v.instruction || "Original"}
                disabled={busy} onClick={() => onUseVersion(v.id)}>{i + 1}</button>
            ))}
          </div>
        )}
        {img?.used_product && <span className="pill dim cc-prod">Uses your product photo</span>}
      </div>

      <div className="cc-actions">
        {failed ? (
          !NO_RETRY.has(concept.error?.kind) && (
            <button className="btn sm primary" disabled={busy} onClick={onRetry}><RotateCcw size={14} /> Retry</button>
          )
        ) : (
          <>
            <button className={`btn sm ${selected ? "vc-picked" : ""}`} disabled={busy} onClick={onSelect}>
              {selected ? <><Check size={14} /> Selected</> : "Select"}
            </button>
            <a className="btn sm ghost" href={img.url} download={`${format}-${concept.id}.jpg`}><Download size={14} /> Download</a>
            <button className="btn sm ghost" disabled={busy} onClick={() => setPanel((p) => !p)}>
              <Wand2 size={14} /> Edit & regenerate
            </button>
          </>
        )}
      </div>

      {panel && !failed && (
        <div className="cc-edit">
          <div className="cc-edit-head"><strong>What should change?</strong><button className="icon-btn" onClick={() => setPanel(false)} aria-label="Close"><X size={14} /></button></div>
          <div className="chips">
            {CATEGORIES.map((c) => (
              <button key={c.key} type="button" className={`chip ${cat === c.key ? "on" : ""}`} onClick={() => setCat(c.key)}>{c.label}</button>
            ))}
          </div>
          <div className="cc-presets">
            {presets.map((p) => <button key={p} type="button" className="tag cc-preset" onClick={() => setText(p)}>{p}</button>)}
          </div>
          <textarea rows={3} maxLength={400} value={text} onChange={(e) => setText(e.target.value)}
            placeholder="Describe the change, e.g. “Make the background a sunny beach and keep the product centred”" />
          <div className="cc-edit-foot">
            <small className="muted">{text.length}/400 · the previous version is kept</small>
            <button className="btn primary sm" disabled={busy || text.trim().length < 3} onClick={apply}>
              {busy ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Regenerate
            </button>
          </div>
        </div>
      )}

      {img && (
        <button className="cc-prompt-toggle" onClick={() => setShowPrompt((s) => !s)}>
          {showPrompt ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Image prompt sent to the AI
        </button>
      )}
      {showPrompt && img && <pre className="cc-prompt">{img.prompt}</pre>}
    </article>
  );
}
