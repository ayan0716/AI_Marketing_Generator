import { useState } from "react";
import { Check, Copy, RefreshCw, Loader2, CheckCircle2 } from "lucide-react";

const LABELS = {
  hook: "Hook", main_message: "Main message", call_to_action: "Call to action", hashtags: "Hashtags",
  introduction: "Introduction", value_proposition: "Value proposition", main_content: "Main content",
  headline: "Headline", primary_text: "Primary text", short_description: "Short description (optional)",
  video_title: "Video title", description: "Description", thumbnail_concept: "Thumbnail concept", frames: "Story frames",
};
const ORDER = {
  instagram: ["hook", "main_message", "call_to_action", "hashtags"],
  instagram_story: ["hook", "frames", "call_to_action"],
  linkedin: ["introduction", "value_proposition", "main_content", "call_to_action", "hashtags"],
  facebook: ["headline", "primary_text", "call_to_action", "short_description"],
  youtube: ["video_title", "hook", "description", "call_to_action", "thumbnail_concept"],
};

const asText = (key, val) => {
  if (key === "hashtags") return val.join(" ");
  if (key === "frames")
    return val.map((f, i) => `Frame ${i + 1}: ${f.visual}\nText: ${f.text_overlay}${f.interaction ? `\nSticker: ${f.interaction}` : ""}`).join("\n\n");
  return val;
};

export function fullText(platform, v) {
  return ORDER[platform]
    .filter((k) => v[k] && v[k].length)
    .map((k) => `${LABELS[k]}:\n${asText(k, v[k])}`)
    .join("\n\n");
}

async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea"); // fallback for non-HTTPS / older browsers
    ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
}

function CopyBtn({ text, label }) {
  const [done, setDone] = useState(false);
  return (
    <button className="icon-btn" title={`Copy ${label}`} onClick={async () => { await copyToClipboard(text); setDone(true); setTimeout(() => setDone(false), 1400); }}>
      {done ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

function Field({ k, v }) {
  const text = asText(k, v);
  return (
    <div className="vc-field">
      <div className="vc-field-head"><span>{LABELS[k]}</span><CopyBtn text={text} label={LABELS[k]} /></div>
      {k === "hashtags" ? (
        <div className="tags">{v.map((h) => <span className="tag metric" key={h}>{h}</span>)}</div>
      ) : k === "frames" ? (
        <ol className="vc-frames">{v.map((f, i) => (
          <li key={i}><strong>{f.text_overlay}</strong><em>{f.visual}</em>{f.interaction && <span className="tag">{f.interaction}</span>}</li>
        ))}</ol>
      ) : (
        <p className={k === "hook" || k === "headline" || k === "video_title" ? "vc-lead" : ""}>{v}</p>
      )}
    </div>
  );
}

export default function VariationCard({ platform, index, variation, selected, busy, onSelect, onRegenerate }) {
  return (
    <article className={`card vc ${selected ? "selected" : ""}`}>
      <header>
        <div>
          <span className="vc-eyebrow">Version {index + 1}</span>
          <span className="vc-angle">{variation.angle}</span>
        </div>
        {selected && <span className="pill vc-badge"><CheckCircle2 size={13} /> Preferred</span>}
      </header>
      <div className={`vc-body ${busy ? "dim" : ""}`}>
        {ORDER[platform].filter((k) => variation[k] && variation[k].length).map((k) => <Field key={k} k={k} v={variation[k]} />)}
      </div>
      <footer className="vc-foot">
        <button className={`btn sm ${selected ? "vc-picked" : ""}`} onClick={onSelect}>{selected ? <><Check size={14} /> Selected</> : "Select this version"}</button>
        <CopyAll text={fullText(platform, variation)} />
        <button className="btn sm ghost" disabled={busy} onClick={onRegenerate}>
          {busy ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Regenerate
        </button>
      </footer>
    </article>
  );
}

function CopyAll({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button className="btn sm ghost" onClick={async () => { await copyToClipboard(text); setDone(true); setTimeout(() => setDone(false), 1400); }}>
      {done ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy all</>}
    </button>
  );
}
