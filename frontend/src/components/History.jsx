import { Trash2, ChevronRight, Inbox } from "lucide-react";

export default function History({ items, onOpen, onDelete, loading }) {
  if (loading) return <div className="card empty">Loading campaigns...</div>;
  if (!items.length)
    return (
      <div className="card empty">
        <Inbox size={32} />
        <h3>No campaigns yet</h3>
        <p className="muted">Generate your first marketing strategy and it will show up here.</p>
      </div>
    );
  return (
    <div className="history">
      {items.map((c) => (
        <div className="card h-item" key={c.id} onClick={() => onOpen(c.id)}>
          <div className="h-main">
            <strong>{c.product_name}</strong>
            <div className="meta">
              <span className="pill">{c.platform}</span>
              <span className="pill">{c.objective}</span>
              <span className="pill">{c.tone}</span>
              <span className="pill dim">{c.language}</span>
            </div>
          </div>
          <time>{new Date(c.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</time>
          <button
            className="icon-btn danger"
            title="Delete"
            onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
          >
            <Trash2 size={16} />
          </button>
          <ChevronRight size={18} className="chev" />
        </div>
      ))}
    </div>
  );
}
