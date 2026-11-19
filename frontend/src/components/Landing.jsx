import {
  Sparkles, ArrowRight, Target, Layers, Languages, ShieldCheck, Database, Zap,
  FileText, Wand2, Rocket, CheckCircle2, TrendingUp, Users,
} from "lucide-react";

const FEATURES = [
  { icon: Target, title: "Audience intelligence", text: "Demographics, psychographics and pain points mapped from your brief." },
  { icon: Layers, title: "Structured strategy", text: "Campaign idea, selling points, tone and CTA in a clean, reusable format." },
  { icon: Languages, title: "12 languages", text: "Generate strategies in English, Urdu, Arabic, Spanish and more." },
  { icon: Zap, title: "Multi-platform", text: "Tuned for Instagram, LinkedIn, TikTok, YouTube, Email, Google Ads and blogs." },
  { icon: Database, title: "AI image creatives", text: "Multiple visual concepts per platform, with your product photo, regenerated on demand." },
  { icon: ShieldCheck, title: "Validated input", text: "Smart validation keeps bad or incomplete briefs from reaching the AI." },
];

const STEPS = [
  { icon: FileText, title: "Describe your product", text: "Add product details, audience, platform, objective, tone and language." },
  { icon: Wand2, title: "AI builds the strategy", text: "A structured prompt turns your brief into a full marketing strategy." },
  { icon: Rocket, title: "Use it everywhere", text: "Copy, download or feed it into content generation in the next phases." },
];

function PreviewMock() {
  return (
    <div className="lp-mock">
      <div className="lp-mock-card main">
        <div className="lp-mock-top"><i /><i /><i /></div>
        <p className="lp-eyebrow">Campaign idea</p>
        <h4>EcoSip Bottle: Made for the planet-first generation</h4>
        <p className="lp-mock-hook">"Sip smart. Waste less."</p>
        <div className="lp-mock-tags"><span>Instagram</span><span>Friendly</span><span>Sales</span></div>
        <div className="lp-mock-bars">
          <div><label>Audience fit</label><b style={{ width: "88%" }} /></div>
          <div><label>Message clarity</label><b style={{ width: "94%" }} /></div>
          <div><label>Platform match</label><b style={{ width: "81%" }} /></div>
        </div>
      </div>
      <div className="lp-float f1"><Users size={16} /> <div><strong>Gen Z & Millennials</strong><small>Target audience</small></div></div>
      <div className="lp-float f2"><TrendingUp size={16} /> <div><strong>+38% engagement</strong><small>Projected goal</small></div></div>
      <div className="lp-float f3"><CheckCircle2 size={16} /> <div><strong>Try it today</strong><small>Call to action</small></div></div>
    </div>
  );
}

export default function Landing({ onStart, onHistory }) {
  return (
    <div className="landing">
      <section className="lp-hero">
        <div className="lp-copy">
          <span className="lp-badge"><Sparkles size={14} /> Generative AI marketing platform</span>
          <h1>
            Turn product ideas into <span className="lp-hl">winning marketing</span> strategies
          </h1>
          <p>
            Enter your product and campaign details. MarketMind AI builds a structured strategy - audience,
            selling points, tone, call-to-action and content types - in seconds.
          </p>
          <div className="lp-cta">
            <button className="btn primary lg-inline" onClick={onStart}>Start a campaign <ArrowRight size={18} /></button>
            <button className="btn ghost lg-inline" onClick={onHistory}>View history</button>
          </div>
          <div className="lp-stats">
            <div><strong>9</strong><span>Platforms</span></div>
            <div><strong>12</strong><span>Languages</span></div>
            <div><strong>3</strong><span>AI providers</span></div>
          </div>
        </div>
        <PreviewMock />
      </section>

      <section className="lp-section">
        <div className="lp-head">
          <span className="lp-kicker">Features</span>
          <h2>Everything you need to plan a campaign</h2>
          <p>Built for marketers, founders and agencies who want a solid strategy before creating content.</p>
        </div>
        <div className="lp-grid">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <div className="lp-feature" key={title}>
              <span className="lp-ico"><Icon size={20} /></span>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-head">
          <span className="lp-kicker">How it works</span>
          <h2>From brief to strategy in three steps</h2>
        </div>
        <div className="lp-steps">
          {STEPS.map(({ icon: Icon, title, text }, i) => (
            <div className="lp-step" key={title}>
              <span className="lp-num">{i + 1}</span>
              <span className="lp-ico"><Icon size={20} /></span>
              <h3>{title}</h3>
              <p>{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-band">
        <h2>Ready to plan your next campaign?</h2>
        <p>Create your first AI marketing strategy now.</p>
        <button className="btn light lg-inline" onClick={onStart}>Get started free <ArrowRight size={18} /></button>
      </section>
    </div>
  );
}
