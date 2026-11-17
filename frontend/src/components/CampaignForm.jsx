import { useState } from "react";
import { Sparkles, Loader2, AlertCircle } from "lucide-react";

const LIMITS = {
  product_name: { min: 2, max: 100, label: "Product name" },
  product_description: { min: 20, max: 2000, label: "Product description" },
  target_audience: { min: 5, max: 500, label: "Target audience" },
};

const EMPTY = {
  product_name: "",
  product_description: "",
  target_audience: "",
  platform: "",
  objective: "",
  tone: "",
  language: "English",
};

const SAMPLE = {
  product_name: "EcoSip Bottle",
  product_description:
    "A reusable stainless steel water bottle that keeps drinks cold for 24 hours and hot for 12, made from recycled materials with a leak-proof lid.",
  target_audience: "Eco-conscious students and office workers aged 18-35 who care about sustainability",
  platform: "Instagram",
  objective: "Sales / Conversions",
  tone: "Friendly",
  language: "English",
};

function validate(v) {
  const e = {};
  for (const [key, { min, max, label }] of Object.entries(LIMITS)) {
    const val = v[key].trim();
    if (!val) e[key] = `${label} is required.`;
    else if (val.length < min) e[key] = `${label} must be at least ${min} characters.`;
    else if (val.length > max) e[key] = `${label} must be at most ${max} characters.`;
    else if (!/\p{L}/u.test(val)) e[key] = "Please enter meaningful text, not only numbers or symbols.";
  }
  if (!v.platform) e.platform = "Choose a marketing platform.";
  if (!v.objective) e.objective = "Choose a campaign objective.";
  if (!v.tone) e.tone = "Choose a tone.";
  return e;
}

function Field({ label, error, hint, children, required = true }) {
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      <label>
        {label} {required && <span className="req">*</span>}
      </label>
      {children}
      {error ? (
        <p className="err"><AlertCircle size={13} /> {error}</p>
      ) : (
        hint && <p className="hint">{hint}</p>
      )}
    </div>
  );
}

function Chips({ value, options, onChange }) {
  return (
    <div className="chips">
      {options.map((o) => (
        <button type="button" key={o} className={`chip ${value === o ? "on" : ""}`} onClick={() => onChange(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

export default function CampaignForm({ options, loading, serverErrors, onSubmit }) {
  const [v, setV] = useState(EMPTY);
  const [touched, setTouched] = useState({});
  const clientErrors = validate(v);
  const errors = { ...serverErrors };
  for (const k of Object.keys(clientErrors)) if (touched[k] || touched.__all) errors[k] = clientErrors[k];

  const set = (k) => (val) => {
    setV((p) => ({ ...p, [k]: val }));
    setTouched((p) => ({ ...p, [k]: true }));
  };
  const text = (k) => ({
    value: v[k],
    onChange: (e) => set(k)(e.target.value),
    onBlur: () => setTouched((p) => ({ ...p, [k]: true })),
  });

  const submit = (e) => {
    e.preventDefault();
    setTouched({ __all: true });
    if (Object.keys(clientErrors).length) return;
    onSubmit({
      ...v,
      product_name: v.product_name.trim(),
      product_description: v.product_description.trim(),
      target_audience: v.target_audience.trim(),
    });
  };

  const count = (k) => (
    <span className={`count ${v[k].length > LIMITS[k].max ? "over" : ""}`}>
      {v[k].length}/{LIMITS[k].max}
    </span>
  );

  return (
    <form className="card form" onSubmit={submit} noValidate>
      <div className="form-head">
        <div>
          <h2>Campaign brief</h2>
          <p className="muted">Tell us about your product. The AI turns it into a structured marketing strategy.</p>
        </div>
        <button type="button" className="btn ghost sm" onClick={() => { setV(SAMPLE); setTouched({}); }}>
          Fill sample
        </button>
      </div>

      <div className="section-label"><span>1</span> Product</div>
      <div className="grid-2">
        <Field label="Product name" error={errors.product_name}>
          <input type="text" placeholder="e.g. EcoSip Bottle" maxLength={120} {...text("product_name")} />
        </Field>
        <Field label="Target audience" error={errors.target_audience} hint="Who are you trying to reach?">
          <input type="text" placeholder="e.g. Eco-conscious students aged 18-35" {...text("target_audience")} />
        </Field>
      </div>
      <Field label="Product description" error={errors.product_description} hint="Features, benefits, what makes it different.">
        <textarea rows={4} placeholder="Describe what your product is and what it does..." {...text("product_description")} />
        {count("product_description")}
      </Field>

      <div className="section-label"><span>2</span> Campaign</div>
      <Field label="Marketing platform" error={errors.platform}>
        <Chips value={v.platform} options={options.platforms} onChange={set("platform")} />
      </Field>
      <Field label="Campaign objective" error={errors.objective}>
        <Chips value={v.objective} options={options.objectives} onChange={set("objective")} />
      </Field>

      <div className="section-label"><span>3</span> Voice</div>
      <Field label="Tone" error={errors.tone}>
        <Chips value={v.tone} options={options.tones} onChange={set("tone")} />
      </Field>
      <Field label="Output language" error={errors.language} required={false}>
        <select value={v.language} onChange={(e) => set("language")(e.target.value)}>
          {options.languages.map((l) => <option key={l}>{l}</option>)}
        </select>
      </Field>

      <button className="btn primary lg" type="submit" disabled={loading}>
        {loading ? <><Loader2 size={18} className="spin" /> Generating strategy...</> : <><Sparkles size={18} /> Generate marketing strategy</>}
      </button>
    </form>
  );
}
