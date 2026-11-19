import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowLeft, Check, Download, ImagePlus, Instagram, Linkedin, Facebook, Youtube, Film, Loader2, Sparkles,
  Trash2, Upload, X,
} from "lucide-react";
import { api } from "../api.js";
import CreativeCard from "./CreativeCard.jsx";

const ICONS = { instagram_post: Instagram, instagram_story: Film, linkedin_creative: Linkedin, facebook_ad: Facebook, youtube_thumbnail: Youtube };
const STEPS = ["Reading strategy and product details", "Writing platform-specific image prompts", "Sending prompts to the image model", "Validating and saving the images"];

function Rendering({ n, concepts }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((p) => Math.min(p + 1, STEPS.length - 1)), 3500);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card generating">
      <div className="orb"><ImagePlus size={28} /></div>
      <h3>Creating {n * concepts} visuals for {n} {n === 1 ? "format" : "formats"}</h3>
      <ul>
        {STEPS.map((s, k) => (
          <li key={s} className={k < i ? "done" : k === i ? "now" : ""}>
            {k < i ? <Check size={15} /> : k === i ? <Loader2 size={15} className="spin" /> : <span className="dot" />}{s}
          </li>
        ))}
      </ul>
      <p className="muted">Image generation can take up to a minute.</p>
    </div>
  );
}

function Lightbox({ concept, format, onClose }) {
  useEffect(() => {
    const k = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  const img = concept.image;
  return (
    <div className="lb" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="lb-in" onClick={(e) => e.stopPropagation()}>
        <button className="lb-x icon-btn" onClick={onClose} aria-label="Close"><X size={18} /></button>
        <div className="lb-img"><img src={img.url} alt={concept.name} /></div>
        <aside>
          <span className="vc-eyebrow">{concept.style_label}</span>
          <h3>{concept.name}</h3>
          <p>{concept.concept_summary}</p>
          <dl>
            <dt>Visual style</dt><dd>{concept.visual_style}</dd>
            <dt>Composition</dt><dd>{concept.composition}</dd>
            <dt>Background</dt><dd>{concept.background}</dd>
            <dt>Lighting</dt><dd>{concept.lighting}</dd>
            <dt>Product placement</dt><dd>{concept.product_placement}</dd>
            <dt>Mood</dt><dd>{concept.mood}</dd>
            <dt>Size</dt><dd>{img.width} × {img.height}px · {img.provider}{img.model !== img.provider ? ` · ${img.model}` : ""}</dd>
          </dl>
          <a className="btn primary sm" href={img.url} download={`${format}-${concept.id}.jpg`}><Download size={14} /> Download image</a>
        </aside>
      </div>
    </div>
  );
}

const readAsDataUrl = (file) => new Promise((res, rej) => {
  const r = new FileReader();
  r.onload = () => res(r.result);
  r.onerror = () => rej(new Error("Could not read that file."));
  r.readAsDataURL(file);
});

export default function CreativeStudio({ campaign, onBack, onError }) {
  const id = campaign.id;
  const [info, setInfo] = useState(null);       // formats + provider status
  const [chosen, setChosen] = useState([]);
  const [count, setCount] = useState(3);
  const [items, setItems] = useState({});        // format -> saved doc
  const [errors, setErrors] = useState({});      // format -> message
  const [tab, setTab] = useState(null);
  const [busy, setBusy] = useState(false);
  const [busyId, setBusyId] = useState("");      // concept id currently regenerating
  const [product, setProduct] = useState(null);
  const [useProduct, setUseProduct] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [zoom, setZoom] = useState(null);
  const fileRef = useRef(null);

  const load = useCallback(async () => {
    const [meta, saved, prod] = await Promise.all([api.creativeFormats(), api.listCreatives(id), api.getProductImage(id)]);
    setInfo(meta);
    setChosen((c) => (c.length ? c : meta.formats.map((f) => f.key)));
    const map = Object.fromEntries(saved.items.map((d) => [d.format, d]));
    setItems(map);
    setProduct(prod.product_image);
    setTab((t) => t || meta.formats.find((f) => map[f.key])?.key || null);
  }, [id]);

  useEffect(() => {
    setItems({}); setErrors({}); setTab(null);
    load().catch((e) => onError(e.message));
  }, [load, onError]);

  const toggle = (k) => setChosen((c) => (c.includes(k) ? c.filter((x) => x !== k) : [...c, k]));

  const upload = async (file) => {
    if (!file) return;
    if (!/^image\/(png|jpe?g|webp)$/.test(file.type)) { onError("Upload a PNG, JPG or WebP image."); return; }
    if (file.size > 5 * 1024 * 1024) { onError("The image is larger than 5 MB."); return; }
    setUploading(true); onError("");
    try {
      const res = await api.uploadProductImage(id, await readAsDataUrl(file));
      setProduct(res.product_image); setUseProduct(true);
    } catch (e) { onError(e.message); }
    setUploading(false);
    if (fileRef.current) fileRef.current.value = "";
  };

  const removeProduct = async () => {
    try { await api.deleteProductImage(id); setProduct(null); } catch (e) { onError(e.message); }
  };

  const generate = async () => {
    setBusy(true); setErrors({}); onError("");
    try {
      const { results } = await api.generateCreatives(id, chosen, count, useProduct && !!product);
      const errs = {}, next = { ...items };
      for (const [k, r] of Object.entries(results)) { if (r.error) errs[k] = r.error; else next[k] = r.creatives; }
      setItems(next); setErrors(errs);
      setTab(chosen.find((k) => next[k]) || tab);
    } catch (e) {
      onError(e.message); // rate limit, invalid key, safety block, provider down ...
    }
    setBusy(false);
  };

  // wraps per-card operations: spinner on the card, error banner on failure, previous image kept
  const act = async (fmt, cid, fn) => {
    setBusyId(cid); onError("");
    try {
      const doc = await fn();
      setItems((m) => ({ ...m, [fmt]: doc }));
      return true;
    } catch (e) {
      onError(e.message);
      if (fmt in items) load().catch(() => {}); // refresh so a failed retry shows its latest error
      return false;
    } finally { setBusyId(""); }
  };

  const select = async (fmt, cid) => {
    setItems((m) => ({ ...m, [fmt]: { ...m[fmt], selected_concept_id: cid } })); // optimistic
    try { await api.selectCreative(id, fmt, cid); } catch (e) { onError(e.message); load(); }
  };

  const doc = tab && items[tab];
  const generated = (info?.formats || []).filter((f) => items[f.key]);
  const labelOf = (k) => info?.formats.find((f) => f.key === k)?.label || k;
  const specOf = (k) => info?.formats.find((f) => f.key === k);
  const productOn = useProduct && !!product;

  return (
    <div className="cs">
      <div className="cs-top">
        <button className="btn sm" onClick={onBack}><ArrowLeft size={14} /> Back to content</button>
        <div className="meta"><span className="pill">{campaign.product_name}</span><span className="pill dim">{campaign.tone}</span><span className="pill dim">{campaign.objective}</span></div>
      </div>

      {info?.notice && <div className={`banner ${info.ready ? "info" : "warn"}`}><AlertTriangle size={16} /> <span>{info.notice}</span></div>}

      <section className="card cs-gen cg">
        <div className="cg-left">
          <h3>1. Choose creative formats</h3>
          <div className="chips">
            {(info?.formats || []).map((f) => {
              const Icon = ICONS[f.key] || Sparkles;
              return (
                <button type="button" key={f.key} title={`${f.summary} (${f.aspect})`} className={`chip ${chosen.includes(f.key) ? "on" : ""}`} onClick={() => toggle(f.key)}>
                  <Icon size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />{f.label} <small>· {f.aspect}</small>
                </button>
              );
            })}
          </div>

          <h3 className="cg-h">2. Product photo <span className="muted">(optional)</span></h3>
          <div className="prod">
            {product ? (
              <>
                <img src={product.url} alt="Your product" />
                <div className="prod-info">
                  <strong>Product photo ready</strong>
                  <label className="check"><input type="checkbox" checked={useProduct} onChange={(e) => setUseProduct(e.target.checked)} /> Place it in the creatives</label>
                  {info && !info.supports_product_image && <small className="muted">The current image provider cannot use a product photo.</small>}
                </div>
                <button className="icon-btn danger" title="Remove photo" onClick={removeProduct}><Trash2 size={16} /></button>
              </>
            ) : (
              <button type="button" className="drop" disabled={uploading} onClick={() => fileRef.current?.click()}
                onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); upload(e.dataTransfer.files?.[0]); }}>
                {uploading ? <Loader2 size={20} className="spin" /> : <Upload size={20} />}
                <span><strong>Upload your product photo</strong><small>PNG, JPG or WebP · up to 5 MB · a clear photo on a plain background works best</small></span>
              </button>
            )}
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => upload(e.target.files?.[0])} />
          </div>
        </div>

        <div className="cs-gen-actions cg-right">
          <div className="field"><label>Concepts per format</label>
            <select value={count} onChange={(e) => setCount(+e.target.value)}>{[1, 2, 3, 4].map((n) => <option key={n}>{n}</option>)}</select>
          </div>
          <button className="btn primary lg-inline" disabled={busy || !chosen.length || !info} onClick={generate}>
            {busy ? <><Loader2 size={16} className="spin" /> Creating…</> : <><ImagePlus size={16} /> {generated.length ? "Generate again" : "Generate visuals"}</>}
          </button>
        </div>
      </section>

      {Object.entries(errors).filter(([, m]) => m).map(([k, m]) => (
        <div className="banner" key={k} role="alert"><AlertTriangle size={16} /><span><strong>{labelOf(k)}:</strong> {m}</span></div>
      ))}

      {busy && <Rendering n={chosen.length} concepts={count} />}

      {!busy && generated.length > 0 && (
        <>
          <nav className="cs-tabs">
            {generated.map((f) => {
              const Icon = ICONS[f.key] || Sparkles;
              return <button key={f.key} className={tab === f.key ? "on" : ""} onClick={() => setTab(f.key)}><Icon size={15} /> {f.label}</button>;
            })}
          </nav>
          {doc && (
            <div className="cs-head">
              <p className="muted">{specOf(tab)?.summary}. Pick your preferred design, download it, or edit and regenerate any concept.</p>
              {productOn && <span className="pill dim">Product photo attached</span>}
            </div>
          )}
          {doc?.warnings?.map((w) => <div className="banner warn" key={w}><AlertTriangle size={16} /> {w}</div>)}
          <div className={`cc-grid ${tab === "instagram_story" ? "tall" : ""}`}>
            {doc?.concepts.map((c) => (
              <CreativeCard
                key={c.id} concept={c} format={tab} spec={specOf(tab)}
                selected={doc.selected_concept_id === c.id} busy={busyId === c.id}
                onSelect={() => select(tab, c.id)}
                onOpen={() => setZoom({ concept: c, format: tab })}
                onRevise={(text, category) => act(tab, c.id, () => api.reviseCreative(id, tab, c.id, { instructions: text, category }))}
                onRetry={() => act(tab, c.id, () => api.retryCreative(id, tab, c.id))}
                onUseVersion={(vid) => act(tab, c.id, () => api.useVersion(id, tab, c.id, vid))}
              />
            ))}
          </div>
        </>
      )}

      {!busy && generated.length === 0 && (
        <div className="card empty"><ImagePlus size={30} /><h3>No visuals yet</h3><p>Choose formats above and press <strong>Generate visuals</strong>.</p></div>
      )}

      {zoom && <Lightbox concept={zoom.concept} format={zoom.format} onClose={() => setZoom(null)} />}
    </div>
  );
}
