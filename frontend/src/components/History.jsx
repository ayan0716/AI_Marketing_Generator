import { useState } from "react";
import { Trash2, ChevronRight, Inbox, Search, ImageIcon, FileText, CheckCircle2, AlertTriangle, Loader2 } from "lucide-react";

const STATUS = {
  campaign_ready: ["Campaign ready", "good"],
  creatives_ready: ["Visuals ready", ""],
  content_ready: ["Copy ready", ""],
  strategy_ready: ["Strategy only", "dim"],
};

export default function History({ items, onOpen, onDelete, loading }) {
  const [q, setQ] = useState("");
  if (loading) return <div className="card empty">Loading campaigns...</div>;
  if (!items.length)
    return (
      <div className="card empty">
        <Inbox size={32} />
        <h3>No campaigns yet</h3>
        <p className="muted">Run the campaign agent and your saved campaign will show up here.</p>
      </div>
    );
  const term = q.trim().toLowerCase();
  const shown = term
    ? items.filter((c) => [c.product_name, c.platform, c.objective, c.tone, c.title].join(" ").toLowerCase().includes(term))
    : items;
  return (
    <div className="history">
      <div className="ag-search">
        <Search size={16} />
        <input type="search" placeholder="Search saved campaigns by product, platform, objective…" value={q} onChange={(e) => setQ(e.target.value)} />
        <span className="muted">{shown.length} of {items.length}</span>
      </div>
      {!shown.length && <div className="card empty"><h3>No match</h3><p className="muted">Nothing in your history matches “{q}”.</p></div>}
      {shown.map((c) => {
        const [label, kind] = STATUS[c.status] || [c.status || "Saved", "dim"];
        return (
          <div className="card h-item ag-h" key={c.id} onClick={() => onOpen(c.id)}>
            <div className="ag-h-thumb">
              {c.thumbnail ? <img src={c.thumbnail} alt="" loading="lazy" /> : <ImageIcon size={22} />}
            </div>
            <div className="h-main">
              <strong>{c.product_name}</strong>
              {c.title && <span className="muted ag-h-title">{c.title}</span>}
              <div className="meta">
                <span className="pill">{c.platform}</span>
                <span className="pill">{c.objective}</span>
                <span className="pill dim">{c.tone}</span>
                <span className={`pill ag-st ${kind}`}>{c.active_run_status ? <><Loader2 size={11} className="spin" /> Running</> : label}</span>
                {c.stale && <span className="pill ag-st warn"><AlertTriangle size={11} /> Strategy changed</span>}
              </div>
              <div className="ag-h-counts muted">
                <span><FileText size={13} /> {c.copy_count} copy</span>
                <span><ImageIcon size={13} /> {c.image_count} visual sets</span>
                {c.asset_count > 0 && <span><CheckCircle2 size={13} /> {c.approved_count}/{c.asset_count} approved</span>}
              </div>
            </div>
            <time>{new Date(c.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</time>
            <button className="icon-btn danger" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}>
              <Trash2 size={16} />
            </button>
            <ChevronRight size={18} className="chev" />
          </div>
        );
      })}
    </div>
  );
}
