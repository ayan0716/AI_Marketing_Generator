import { useState } from "react";
import { ShieldCheck } from "lucide-react";
import CampaignForm from "./CampaignForm.jsx";
import "../phase4.css";

// Step 1: the campaign brief that starts the whole automatic workflow.
export default function AgentBrief({ options, loading, serverErrors, initial, onSubmit }) {
  const [variations, setVariations] = useState(2);
  const [concepts, setConcepts] = useState(2);
  const [images, setImages] = useState(true);
  const [review, setReview] = useState(false);

  return (
    <CampaignForm
      options={options}
      loading={loading}
      serverErrors={serverErrors}
      initial={initial}
      title="Campaign brief"
      intro="One brief is all the agent needs. It creates the strategy, plans the assets, writes the copy, writes the image prompts and generates the visuals."
      submitLabel="Run the campaign agent"
      loadingLabel="Starting the agent..."
      onSubmit={(payload) => onSubmit({ ...payload, variations, concepts, generate_images: images, require_plan_approval: review })}
    >
      <div className="section-label"><span>4</span> Agent options</div>
      <div className="ag-opts">
        <div className="field">
          <label>Copy variations per asset</label>
          <select value={variations} onChange={(e) => setVariations(+e.target.value)}>{[1, 2, 3].map((n) => <option key={n}>{n}</option>)}</select>
        </div>
        <div className="field">
          <label>Image concepts per asset</label>
          <select value={concepts} onChange={(e) => setConcepts(+e.target.value)} disabled={!images}>{[1, 2, 3].map((n) => <option key={n}>{n}</option>)}</select>
        </div>
        <label className="check ag-check">
          <input type="checkbox" checked={images} onChange={(e) => setImages(e.target.checked)} />
          <span><strong>Generate visual creatives</strong><small>Turn this off to produce copy and image prompts only.</small></span>
        </label>
        <label className="check ag-check">
          <input type="checkbox" checked={review} onChange={(e) => setReview(e.target.checked)} />
          <span><strong>Pause for my approval after planning</strong><small>Review (and edit) the asset list before any copy or images are generated.</small></span>
        </label>
      </div>
      <div className="ag-safe">
        <ShieldCheck size={16} />
        <span>The agent only creates <b>drafts</b>. It never publishes, posts, emails or spends money — you approve each asset and export it yourself.</span>
      </div>
    </CampaignForm>
  );
}
