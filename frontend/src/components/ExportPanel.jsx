import { useState } from "react";
import { Download, Lock, ShieldCheck, Send } from "lucide-react";

// Step 10: the only way content leaves the app. Needs approved assets and an explicit confirmation.
export default function ExportPanel({ approved, total, onExport, busy }) {
  const [ok, setOk] = useState(false);
  const [format, setFormat] = useState("markdown");
  return (
    <section className="card ag-export">
      <div className="ag-export-head">
        <span className="ico"><ShieldCheck size={16} /></span>
        <div>
          <h3>Approve &amp; export</h3>
          <p className="muted">
            Nothing is published automatically. Approve the assets you like, then export them as a file and post them yourself.
            <b> {approved} of {total}</b> approved.
          </p>
        </div>
      </div>
      <label className="check ag-check">
        <input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />
        <span><strong>I reviewed the approved assets</strong><small>I understand this creates a file only — no post, email or ad is sent anywhere.</small></span>
      </label>
      <div className="ag-export-actions">
        <select value={format} onChange={(e) => setFormat(e.target.value)} aria-label="Export format">
          <option value="markdown">Markdown (.md)</option>
          <option value="json">JSON (.json)</option>
        </select>
        <button className="btn primary" disabled={!ok || !approved || busy} onClick={() => onExport(format)}>
          <Download size={15} /> Export approved assets
        </button>
        <button className="btn ghost" disabled title="Direct publishing is disabled. Export the approved assets and post them manually.">
          <Lock size={14} /> <Send size={14} /> Publish to platforms
        </button>
      </div>
      <small className="muted">Direct publishing to social platforms is intentionally disabled in this app.</small>
    </section>
  );
}
