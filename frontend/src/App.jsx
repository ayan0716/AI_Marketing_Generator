import { useCallback, useEffect, useState } from "react";
import { Wand2, Activity, Loader2, Check, Menu, X } from "lucide-react";
import { api, ApiError } from "./api.js";
import Landing from "./components/Landing.jsx";
import CampaignForm from "./components/CampaignForm.jsx";
import StrategyView, { ErrorBanner } from "./components/StrategyView.jsx";
import History from "./components/History.jsx";
import ContentStudio from "./components/ContentStudio.jsx";
const STEPS = [
  "Analysing your product brief",
  "Profiling the target audience",
  "Crafting the campaign idea",
  "Structuring the marketing strategy",
];
const THEMES = [
  { id: "blue", label: "SaaS Blue", color: "#3b5bfd" },
  { id: "green", label: "Fresh Green", color: "#16a34a" },
  { id: "orange", label: "Warm Orange", color: "#f97316" },
  { id: "dark", label: "Midnight", color: "#19e3a1" },
];
function Generating() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((p) => Math.min(p + 1, STEPS.length - 1)), 2200);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="card generating">
      <div className="orb"><Wand2 size={28} /></div>
      <h3>Building your strategy</h3>
      <ul>
        {STEPS.map((s, n) => (
          <li key={s} className={n < i ? "done" : n === i ? "now" : ""}>
            {n < i ? <Check size={15} /> : n === i ? <Loader2 size={15} className="spin" /> : <span className="dot" />}
            {s}
          </li>
        ))}
      </ul>
    </div>
  );
}
function loadTheme() {
  try { return localStorage.getItem("mm-theme") || "blue"; } catch { return "blue"; }
}
export default function App() {
  const [view, setView] = useState("home"); // home | create | result | content | history
  const [options, setOptions] = useState(null);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [history, setHistory] = useState([]);
  const [histLoading, setHistLoading] = useState(false);
  const [health, setHealth] = useState(null);
  const [llm, setLlm] = useState(null);
  const [testing, setTesting] = useState(false);
  const [theme, setTheme] = useState(loadTheme);
  const [menu, setMenu] = useState(false);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("mm-theme", theme); } catch { /* ignore */ }
  }, [theme]);
  useEffect(() => {
    api.options().then(setOptions).catch((e) => setError(e.message));
    api.health().then(setHealth).catch(() => setHealth({ status: "down" }));
  }, []);
  const loadHistory = useCallback(async () => {
    setHistLoading(true);
    try { setHistory(await api.listCampaigns()); } catch (e) { setError(e.message); }
    setHistLoading(false);
  }, []);
  useEffect(() => { if (view === "history") loadHistory(); }, [view, loadHistory]);
  const testLlm = async () => {
    setTesting(true);
    try { setLlm(await api.llmTest()); } catch (e) { setLlm({ ok: false, error: e.message }); }
    setTesting(false);
  };
  const go = (v) => { setView(v); setError(""); setMenu(false); window.scrollTo({ top: 0 }); };
  const generate = async (payload) => {
    setError(""); setFieldErrors({}); setLoading(true);
    try {
      setResult(await api.createStrategy(payload));
      go("result");
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) setFieldErrors(e.fieldErrors);
      setError(e.message);
    }
    setLoading(false);
  };
  const openCampaign = async (id) => {
    try { setResult(await api.getCampaign(id)); go("result"); } catch (e) { setError(e.message); }
  };
  const remove = async (id) => {
    if (!confirm("Delete this campaign and its strategy?")) return;
    try { await api.deleteCampaign(id); setHistory((h) => h.filter((c) => c.id !== id)); } catch (e) { setError(e.message); }
  };
  const dbOk = health?.status === "ok";
  const llmCls = llm ? (llm.ok ? "ok" : "bad") : "";
  const titles = {
    create: ["Create a marketing strategy", "Enter product and campaign details to generate a structured, AI-powered strategy."],
    result: ["Your marketing strategy", "Structured strategy ready to power content generation."],
    content: ["Platform content", "Turn the strategy into Instagram, LinkedIn, Facebook and YouTube content. Compare variations, copy or regenerate."],
    history: ["Campaign history", "Previously generated campaigns stored in MongoDB."],
  };
  return (
    <div className="app">
      <header className="nav">
        <div className="container nav-in">
          <button className="brand" onClick={() => go("home")}>
            <span className="logo"><Wand2 size={17} /></span> MarketMind<b>AI</b>
          </button>
          <nav className={`links ${menu ? "open" : ""}`}>
            <button className={view === "home" ? "on" : ""} onClick={() => go("home")}>Home</button>
            <button className={view === "create" || view === "result" || view === "content" ? "on" : ""} onClick={() => go("create")}>New campaign</button>
            <button className={view === "history" ? "on" : ""} onClick={() => go("history")}>History</button>
          </nav>
          <div className="nav-right">
            <div className="themes" role="group" aria-label="Theme">
              {THEMES.map((t) => (
                <button
                  key={t.id}
                  title={t.label}
                  aria-label={t.label}
                  className={`swatch ${theme === t.id ? "on" : ""}`}
                  style={{ background: t.color }}
                  onClick={() => setTheme(t.id)}
                />
              ))}
            </div>
            <button className="statuspill" onClick={testLlm} disabled={testing} title="Test LLM connection">
              {testing ? <Loader2 size={13} className="spin" /> : <Activity size={13} />}
              <span className="hide-sm">DB</span><i className={`led ${health ? (dbOk ? "ok" : "bad") : ""}`} />
              <span className="hide-sm">AI</span><i className={`led ${llmCls}`} />
              <span className="hide-sm">{llm ? (llm.ok ? `${llm.provider}` : "failed") : "Test AI"}</span>
            </button>
            <button className="menu-btn" onClick={() => setMenu((m) => !m)} aria-label="Menu">{menu ? <X size={20} /> : <Menu size={20} />}</button>
          </div>
        </div>
        {llm && !llm.ok && <div className="container"><ErrorBanner message={llm.error || "LLM connection failed."} onClose={() => setLlm(null)} /></div>}
      </header>
      {view === "home" && <Landing onStart={() => go("create")} onHistory={() => go("history")} />}
      {view !== "home" && (
        <main className="container page">
          <div className="page-head">
            <h1>{titles[view][0]}</h1>
            <p className="muted">{titles[view][1]}</p>
          </div>
          {error && <ErrorBanner message={error} onClose={() => setError("")} />}
          {view === "create" && options && !loading && (
            <CampaignForm options={options} loading={loading} serverErrors={fieldErrors} onSubmit={generate} />
          )}
          {view === "create" && loading && <Generating />}
          {view === "result" && result && <StrategyView result={result} onNew={() => go("create")} onContent={() => go("content")} />}
          {view === "content" && result && <ContentStudio campaign={result.campaign} onBack={() => go("result")} onError={setError} />}
          {view === "history" && <History items={history} loading={histLoading} onOpen={openCampaign} onDelete={remove} />}
        </main>
      )}
      <footer className="footer">
        <div className="container">
          <span>© 2026 MarketMind AI · Generative AI Internship Project</span>
          <span>FastAPI · React · MongoDB · LLM</span>
        </div>
      </footer>
    </div>
  );
}