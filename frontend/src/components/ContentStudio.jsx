import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Sparkles, AlertTriangle, ArrowLeft, Instagram, Linkedin, Facebook, Youtube, Film, Check, ImagePlus } from "lucide-react";
import { api } from "../api.js";
import VariationCard from "./VariationCard.jsx";

const ICONS = { instagram: Instagram, instagram_story: Film, linkedin: Linkedin, facebook: Facebook, youtube: Youtube };
const STEPS = ["Reading your strategy", "Writing platform-specific copy", "Validating structured output", "Saving variations"];

function Writing({ n }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((p) => Math.min(p + 1, STEPS.length - 1)), 2200);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card generating">
      <div className="orb"><Sparkles size={28} /></div>
      <h3>Writing {n} content {n === 1 ? "format" : "formats"}</h3>
      <ul>
        {STEPS.map((s, k) => (
          <li key={s} className={k < i ? "done" : k === i ? "now" : ""}>
            {k < i ? <Check size={15} /> : k === i ? <Loader2 size={15} className="spin" /> : <span className="dot" />}{s}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ContentStudio({ campaign, onBack, onCreative, onError }) {
  const id = campaign.id;
  const [platforms, setPlatforms] = useState([]);
  const [chosen, setChosen] = useState([]);
  const [count, setCount] = useState(3);
  const [content, setContent] = useState({}); // platform -> saved doc
  const [errors, setErrors] = useState({}); // platform -> message
  const [tab, setTab] = useState(null);
  const [busy, setBusy] = useState(false);
  const [busyKey, setBusyKey] = useState(""); // "instagram" | "instagram:1"

  const load = useCallback(async () => {
    const [plats, saved] = await Promise.all([api.platforms(), api.listContent(id)]);
    setPlatforms(plats);
    setChosen((c) => (c.length ? c : plats.map((p) => p.key)));
    const map = Object.fromEntries(saved.items.map((d) => [d.platform, d]));
    setContent(map);
    setTab((t) => t || plats.find((p) => map[p.key])?.key || null);
  }, [id]);

  useEffect(() => {
    setContent({}); setErrors({}); setTab(null);
    load().catch((e) => onError(e.message));
  }, [load, onError]);

  const toggle = (k) => setChosen((c) => (c.includes(k) ? c.filter((x) => x !== k) : [...c, k]));

  const generate = async () => {
    setBusy(true); setErrors({}); onError("");
    try {
      const { results } = await api.generateContent(id, chosen, count);
      const errs = {}, next = { ...content };
      for (const [k, r] of Object.entries(results)) { if (r.error) errs[k] = r.error; else next[k] = r.content; }
      setContent(next); setErrors(errs);
      setTab(chosen.find((k) => next[k]) || tab);
    } catch (e) {
      onError(e.message);
    }
    setBusy(false);
  };

  const regenerate = async (platform, index) => {
    setBusyKey(index == null ? platform : `${platform}:${index}`); onError("");
    try {
      const doc = await api.regenerate(id, platform, index == null ? { variations: count } : { index });
      setContent((c) => ({ ...c, [platform]: doc }));
      setErrors((e) => ({ ...e, [platform]: undefined }));
    } catch (e) {
      setErrors((x) => ({ ...x, [platform]: e.message }));
    }
    setBusyKey("");
  };

  const select = async (platform, index) => {
    setContent((c) => ({ ...c, [platform]: { ...c[platform], selected_index: index } })); // optimistic
    try { await api.selectVariation(id, platform, index); } catch (e) { onError(e.message); load(); }
  };

  const doc = tab && content[tab];
  const generated = platforms.filter((p) => content[p.key]);
  const labelOf = (k) => platforms.find((p) => p.key === k)?.label || k;

  return (
    <div className="cs">
      <div className="cs-top">
        <button className="btn sm" onClick={onBack}><ArrowLeft size={14} /> Back to strategy</button>
        <div className="meta"><span className="pill">{campaign.product_name}</span><span className="pill dim">{campaign.tone}</span><span className="pill dim">{campaign.language}</span>
          {onCreative && <button className="btn primary sm" onClick={onCreative}><ImagePlus size={14} /> Create visuals</button>}</div>
      </div>

      <section className="card cs-gen">
        <div>
          <h3>Choose platforms</h3>
          <div className="chips">
            {platforms.map((p) => {
              const Icon = ICONS[p.key] || Sparkles;
              return (
                <button type="button" key={p.key} className={`chip ${chosen.includes(p.key) ? "on" : ""}`} onClick={() => toggle(p.key)}>
                  <Icon size={14} style={{ verticalAlign: "-2px", marginRight: 6 }} />{p.label}
                </button>
              );
            })}
          </div>
        </div>
        <div className="cs-gen-actions">
          <div className="field"><label>Variations</label>
            <select value={count} onChange={(e) => setCount(+e.target.value)}>{[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}</select>
          </div>
          <button className="btn primary lg-inline" disabled={busy || !chosen.length} onClick={generate}>
            {busy ? <><Loader2 size={16} className="spin" /> Writing…</> : <><Sparkles size={16} /> {generated.length ? "Generate again" : "Generate content"}</>}
          </button>
        </div>
      </section>

      {Object.entries(errors).filter(([, m]) => m).map(([k, m]) => (
        <div className="banner" key={k} role="alert"><AlertTriangle size={16} /><span><strong>{labelOf(k)}:</strong> {m}</span></div>
      ))}

      {busy && <Writing n={chosen.length} />}

      {!busy && generated.length > 0 && (
        <>
          <nav className="cs-tabs">
            {generated.map((p) => {
              const Icon = ICONS[p.key] || Sparkles;
              return <button key={p.key} className={tab === p.key ? "on" : ""} onClick={() => setTab(p.key)}><Icon size={15} /> {p.label}</button>;
            })}
          </nav>
          {doc && (
            <div className="cs-head">
              <p className="muted">Select your preferred version, copy any field, or regenerate. <span className="pill dim">{doc.provider}{doc.model && doc.model !== doc.provider ? ` · ${doc.model}` : ""}</span></p>
              <button className="btn sm" disabled={!!busyKey} onClick={() => regenerate(tab, null)}>
                {busyKey === tab ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} Regenerate all
              </button>
            </div>
          )}
          {doc?.warnings?.map((w) => <div className="banner warn" key={w}><AlertTriangle size={16} /> {w}</div>)}
          <div className="cs-grid">
            {doc?.variations.map((v, i) => (
              <VariationCard
                key={v.id} platform={tab} index={i} variation={v}
                selected={doc.selected_index === i}
                busy={busyKey === `${tab}:${i}` || busyKey === tab}
                onSelect={() => select(tab, i)}
                onRegenerate={() => regenerate(tab, i)}
              />
            ))}
          </div>
        </>
      )}

      {!busy && generated.length === 0 && (
        <div className="card empty"><Sparkles size={30} /><h3>No content yet</h3><p>Pick the platforms above and press <strong>Generate content</strong>.</p></div>
      )}
    </div>
  );
}