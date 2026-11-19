import { useState } from "react";
import {
  Lightbulb, Users, Star, Mic2, MousePointerClick, LayoutGrid, BarChart3,
  Copy, Download, Check, Plus, ImagePlus, AlertTriangle, Ban, CheckCircle2, Megaphone, ArrowRight,
} from "lucide-react";
function Card({ icon: Icon, title, children, className = "" }) {
  return (
    <section className={`card s-card ${className}`}>
      <h3><span className="ico"><Icon size={16} /></span>{title}</h3>
      {children}
    </section>
  );
}
const List = ({ items }) => (
  <ul className="plain">{items.map((i, n) => <li key={n}>{i}</li>)}</ul>
);
const Tags = ({ items, kind = "" }) => (
  <div className="tags">{items.map((i, n) => <span key={n} className={`tag ${kind}`}>{i}</span>)}</div>
);
export default function StrategyView({ result, onNew, onContent: onContentProp, onCreative }) {
  // Diagnostic: if App.jsx was not updated, say so instead of silently doing nothing.
  const onContent = onContentProp || (() => alert("App.jsx is not updated: StrategyView did not receive the onContent prop. Replace src/App.jsx with the Phase 2 version."));
  const { campaign, strategy } = result;
  const s = strategy.data;
  const [copied, setCopied] = useState(false);
  // Safety net: if App.jsx does not pass onContent, say so instead of doing nothing.
  const goContent = onContent || (() => alert("App.jsx is missing the Phase 2 'content' view. Replace src/App.jsx with the Phase 2 version."));
  const json = JSON.stringify(s, null, 2);
  const copy = async () => {
    await navigator.clipboard.writeText(json);
    setCopied(true);
    setTimeout(() => setCopied(false), 1800);
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([json], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), {
      href: url,
      download: `${campaign.product_name.replace(/\s+/g, "-").toLowerCase()}-strategy.json`,
    });
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="strategy">
      <div className="result-bar">
        <div className="meta">
          <span className="pill">{campaign.platform}</span>
          <span className="pill">{campaign.objective}</span>
          <span className="pill">{campaign.tone}</span>
          <span className="pill">{campaign.language}</span>
          <span className="pill dim">via {strategy.provider}{strategy.model !== strategy.provider ? ` · ${strategy.model}` : ""}</span>
        </div>
        <div className="actions">
          <button className="btn ghost sm" onClick={copy}>{copied ? <Check size={15} /> : <Copy size={15} />} {copied ? "Copied" : "Copy JSON"}</button>
          <button className="btn ghost sm" onClick={download}><Download size={15} /> Download</button>
          <button className="btn sm" onClick={onNew}><Plus size={15} /> New campaign</button>
          <button className="btn primary sm" onClick={goContent}><Megaphone size={15} /> Generate content</button>
          {onCreative && <button className="btn primary sm" onClick={onCreative}><ImagePlus size={15} /> Generate visuals</button>}
        </div>
      </div>
      <section className="hero">
        <p className="eyebrow">Campaign idea · {campaign.product_name}</p>
        <h2>{s.campaign_idea.title}</h2>
        <p className="hook">"{s.campaign_idea.hook}"</p>
        <p className="concept">{s.campaign_idea.concept}</p>
      </section>
      <div className="grid-2 gap">
        <Card icon={Users} title="Target audience">
          <p className="lead">{s.target_audience.summary}</p>
          <h4>Demographics</h4><Tags items={s.target_audience.demographics} />
          <h4>Psychographics</h4><Tags items={s.target_audience.psychographics} />
          <h4>Pain points</h4><List items={s.target_audience.pain_points} />
        </Card>
        <Card icon={Mic2} title="Content tone">
          <p className="lead">{s.content_tone.voice}</p>
          <h4>Style guidelines</h4><List items={s.content_tone.style_guidelines} />
          <h4><CheckCircle2 size={13} className="ok" /> Words to use</h4><Tags items={s.content_tone.words_to_use} kind="good" />
          <h4><Ban size={13} className="bad" /> Words to avoid</h4><Tags items={s.content_tone.words_to_avoid} kind="bad" />
        </Card>
      </div>
      <Card icon={Star} title="Key selling points">
        <div className="usp-grid">
          {s.key_selling_points.map((k, i) => (
            <div className="usp" key={i}>
              <span className="num">{i + 1}</span>
              <strong>{k.point}</strong>
              <p>{k.benefit}</p>
            </div>
          ))}
        </div>
      </Card>
      <div className="grid-2 gap">
        <Card icon={MousePointerClick} title="Call to action" className="cta">
          <div className="cta-main">{s.call_to_action.primary}</div>
          <h4>Alternatives</h4>
          <Tags items={s.call_to_action.alternatives} />
        </Card>
        <Card icon={BarChart3} title="Success metrics">
          <Tags items={s.success_metrics} kind="metric" />
        </Card>
      </div>
      <Card icon={LayoutGrid} title="Suggested content types">
        <div className="types">
          {s.suggested_content_types.map((t, i) => (
            <div className="type" key={i}>
              <strong>{t.type}</strong>
              <p>{t.description}</p>
              <small>{t.why_it_works}</small>
            </div>
          ))}
        </div>
      </Card>
      <button className="btn primary lg" onClick={goContent}>
        <Megaphone size={18} /> Turn this strategy into platform content <ArrowRight size={17} />
      </button>
      {onCreative && (
        <button className="btn lg" onClick={onCreative}>
          <ImagePlus size={18} /> Turn this strategy into AI visual creatives <ArrowRight size={17} />
        </button>
      )}
      <p className="next"><Lightbulb size={14} /> This strategy is saved and drives the content (Phase 2) and image creative (Phase 3) generation.</p>
    </div>
  );
}
export function ErrorBanner({ message, onClose }) {
  return (
    <div className="banner">
      <AlertTriangle size={16} /> <span>{message}</span>
      {onClose && <button onClick={onClose} aria-label="Dismiss">×</button>}
    </div>
  );
}
