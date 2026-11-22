import { useState } from "react";
import {
  Check, ChevronDown, ChevronUp, Copy, Film, ImagePlus, Instagram, Linkedin, Facebook, Youtube, MessageSquareText,
  RefreshCw, RotateCcw, ThumbsDown, ThumbsUp, Type, AlertTriangle, ImageOff,
} from "lucide-react";

const ICON = { instagram_post: Instagram, instagram_story: Film, instagram_reel: Film, promo_caption: MessageSquareText,
  linkedin_post: Linkedin, facebook_ad: Facebook, youtube_video: Youtube };

const pretty = (k) => k.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const HIDE = new Set(["id", "angle"]);

function flatten(data, order) {
  const keys = order || Object.keys(data);
  return keys.filter((k) => !HIDE.has(k) && data[k] !== undefined && data[k] !== "" && !(Array.isArray(data[k]) && !data[k].length)).map((k) => [k, data[k]]);
}

function asText(entries) {
  return entries.map(([k, v]) => {
    if (Array.isArray(v)) {
      if (typeof v[0] === "object") return `${pretty(k)}:\n` + v.map((o, i) => `${i + 1}. ` + Object.values(o).filter(Boolean).join(" | ")).join("\n");
      return `${pretty(k)}: ${v.join(" ")}`;
    }
    return `${pretty(k)}: ${v}`;
  }).join("\n\n");
}

function Value({ k, v }) {
  if (Array.isArray(v)) {
    if (typeof v[0] === "object") {
      return (
        <ol className="vc-frames">
          {v.map((o, i) => (
            <li key={i}>
              <strong>{o.text_overlay || o.on_screen_text}</strong>
              <em>{o.visual}{o.seconds ? ` · ${o.seconds}s` : ""}</em>
              {o.interaction && <span className="tag">{o.interaction}</span>}
            </li>
          ))}
        </ol>
      );
    }
    return <div className="tags">{v.map((t) => <span key={t} className="tag metric">{t}</span>)}</div>;
  }
  return <p className={["hook", "headline", "video_title", "title"].includes(k) ? "vc-lead" : ""}>{v}</p>;
}

export default function AssetCard({ item, busy, locked, onApprove, onCaption, onImage }) {
  const [showPrompt, setShowPrompt] = useState(false);
  const [copied, setCopied] = useState(false);
  const Icon = ICON[item.key] || Type;

  // the selected copy: a Phase 2 variation, or a Phase 4 reel / promo asset
  let data = null, versions = 0;
  if (item.content?.variations?.length) {
    versions = item.content.variations.length;
    data = item.content.variations[Math.min(item.content.selected_index, versions - 1)];
  } else if (item.extra) data = item.extra.data;
  const entries = data ? flatten(data, item.extra_fields) : [];

  const cr = item.creative;
  const concept = cr?.concepts.find((c) => c.id === cr.selected_concept_id) || cr?.concepts.find((c) => c.image);
  const img = concept?.image;
  const generated = !!(data || img);

  const copy = async () => {
    try { await navigator.clipboard.writeText(asText(entries)); } catch { /* clipboard may be blocked */ }
    setCopied(true); setTimeout(() => setCopied(false), 1400);
  };
  const off = busy || locked;

  return (
    <article className={`card ag-asset ${item.approval}`}>
      <header className="ag-asset-head">
        <span className="ico"><Icon size={16} /></span>
        <div>
          <h4>{item.label}</h4>
          {item.reason && <p className="muted">{item.reason}</p>}
        </div>
        <span className={`pill ag-ap ${item.approval}`}>
          {item.approval === "approved" ? "Approved" : item.approval === "rejected" ? "Rejected" : generated ? "Needs your approval" : "Not generated"}
        </span>
      </header>

      {item.error && <div className="banner warn"><AlertTriangle size={16} /><span>{item.error}</span></div>}

      <div className={`ag-asset-body ${img ? "with-img" : ""}`}>
        <div className={`ag-copy ${busy ? "dim" : ""}`}>
          <div className="ag-sec-head">
            <span className="vc-eyebrow">Copy{versions > 1 ? ` · version ${item.content.selected_index + 1} of ${versions}` : ""}</span>
            {entries.length > 0 && <button className="icon-btn" title="Copy text" onClick={copy}>{copied ? <Check size={14} /> : <Copy size={14} />}</button>}
          </div>
          {entries.length ? entries.map(([k, v]) => (
            <div className="vc-field" key={k}>
              <div className="vc-field-head"><span>{pretty(k)}</span></div>
              <Value k={k} v={v} />
            </div>
          )) : <p className="muted">No copy yet.</p>}
        </div>

        {item.has_image && (
          <div className="ag-visual">
            <span className="vc-eyebrow">Visual</span>
            {img ? (
              <>
                <a href={img.url} target="_blank" rel="noreferrer" className={`ag-img ${busy ? "dim" : ""}`} style={{ aspectRatio: `${img.width} / ${img.height}` }}>
                  <img src={img.url} alt={concept.name} loading="lazy" />
                </a>
                <small className="muted">{concept.style_label} · {img.width}×{img.height}px{cr.concepts.length > 1 ? ` · ${cr.concepts.length} concepts` : ""}</small>
                <button className="cc-prompt-toggle ag-pt" onClick={() => setShowPrompt((s) => !s)}>
                  {showPrompt ? <ChevronUp size={14} /> : <ChevronDown size={14} />} Image prompt
                </button>
                {showPrompt && <pre className="cc-prompt ag-pre">{img.prompt}</pre>}
              </>
            ) : (
              <div className="ag-noimg"><ImageOff size={22} /><span>No image yet</span></div>
            )}
          </div>
        )}
      </div>

      <footer className="ag-asset-foot">
        <div className="ag-regen">
          <button className="btn sm ghost" disabled={off} onClick={onCaption} title="Rewrite only the copy of this asset">
            <RefreshCw size={14} /> Regenerate caption
          </button>
          {item.has_image && (
            <button className="btn sm ghost" disabled={off} onClick={onImage} title="Create new image prompts and images for this asset">
              <ImagePlus size={14} /> Regenerate image
            </button>
          )}
        </div>
        <div className="ag-approve">
          {item.approval === "approved" ? (
            <button className="btn sm" disabled={locked} onClick={() => onApprove("pending")}><RotateCcw size={14} /> Undo approval</button>
          ) : (
            <>
              <button className="btn sm ag-no" disabled={locked || !generated || item.approval === "rejected"} onClick={() => onApprove("rejected")}><ThumbsDown size={14} /> Reject</button>
              <button className="btn sm primary" disabled={locked || !generated} onClick={() => onApprove("approved")}><ThumbsUp size={14} /> Approve</button>
            </>
          )}
        </div>
      </footer>
    </article>
  );
}
