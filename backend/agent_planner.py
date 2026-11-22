"""Phase 4, Step 7 - AI campaign planner.

Given the brief and the approved strategy, decide WHICH assets this campaign needs (e.g. for an Instagram
campaign: feed post, story, reel concept and promotional caption). The LLM chooses from the fixed asset catalog,
its answer is validated, and a rule-based plan is used whenever the model is unavailable or answers badly, so
planning can never block the workflow.
"""
import json
import logging

import agent_guard
import llm
from agent_schemas import ASSET_KEYS, ASSETS, PLATFORM_DEFAULTS, asset_meta
from config import get_settings

log = logging.getLogger("agent.planner")

SYSTEM_PROMPT = """You are a senior campaign planner at a digital marketing agency.
You decide which marketing assets a campaign needs, based on the brief and the approved strategy.
Rules:
- Output ONLY one valid JSON object. No markdown fences, no commentary.
- Choose ONLY asset keys from the provided catalog. Never invent keys.
- Pick between 2 and 5 assets that work TOGETHER for the campaign platform and objective (no duplicates).
- Give a one-sentence reason for each asset, grounded in the brief.
- Write 'summary' and every 'reason' in the requested output language.
"""

_REASONS = {
    "instagram_post": "A feed post is the core asset: it carries the main message and hashtags for discovery.",
    "instagram_story": "Stories give a fast, full-screen touchpoint with interactive stickers for engagement.",
    "instagram_reel": "A short video concept earns the widest organic reach on short-form feeds.",
    "promo_caption": "A short offer-led caption can be reused across channels and drives the call to action.",
    "linkedin_post": "A professional post builds credibility with decision makers.",
    "facebook_ad": "Ad copy plus a feed visual is built for clicks and conversions.",
    "youtube_video": "Video packaging (title, hook, thumbnail) captures search and browse traffic.",
}


def default_keys(campaign: dict) -> list[str]:
    keys = list(PLATFORM_DEFAULTS.get(campaign.get("platform", ""), ["promo_caption", "instagram_post"]))
    obj = campaign.get("objective", "")
    if obj == "Sales / Conversions" and "promo_caption" not in keys:
        keys.append("promo_caption")
    if obj in ("Brand Awareness", "Engagement") and campaign.get("platform") == "Instagram" and "instagram_reel" not in keys:
        keys.append("instagram_reel")
    return keys[: agent_guard.MAX_ASSETS_PER_RUN]


def _items(keys: list[str], reasons: dict[str, str] | None = None) -> list[dict]:
    return [{**asset_meta(k), "reason": (reasons or {}).get(k) or _REASONS[k]} for k in keys]


def build_prompt(campaign: dict, strategy: dict) -> str:
    brief = {
        "product_name": campaign["product_name"],
        "target_audience": campaign.get("target_audience"),
        "campaign_platform": campaign["platform"],
        "campaign_objective": campaign["objective"],
        "tone": campaign["tone"],
        "output_language": campaign.get("language", "English"),
    }
    strat = {
        "campaign_idea": strategy.get("campaign_idea"),
        "suggested_content_types": strategy.get("suggested_content_types"),
        "success_metrics": strategy.get("success_metrics"),
    }
    catalog = {k: f"{a['label']} - {a['description']}" for k, a in ASSETS.items()}
    shape = {"summary": "str (1-2 sentences: the plan in plain words)",
             "assets": [{"key": "one key from the catalog", "reason": "str (one sentence)"}]}
    return (
        "CAMPAIGN BRIEF:\n" + json.dumps(brief, ensure_ascii=False, indent=2)
        + "\n\nAPPROVED STRATEGY (extract):\n" + json.dumps(strat, ensure_ascii=False, indent=2)
        + "\n\nASSET CATALOG (choose keys from here):\n" + json.dumps(catalog, ensure_ascii=False, indent=2)
        + "\n\nReturn JSON in exactly this shape:\n" + json.dumps(shape, indent=2)
    )


def parse_plan(raw: str) -> tuple[str, list[dict], list[str]]:
    """Return (summary, [{key, reason}], problems). Never raises on bad model output."""
    try:
        data = llm._extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        return "", [], ["reply was not valid JSON"]
    if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
        return "", [], ["JSON has no 'assets' array"]
    out, problems, seen = [], [], set()
    for i, a in enumerate(data["assets"]):
        key = a.get("key") if isinstance(a, dict) else a
        if key not in ASSETS:
            problems.append(f"asset {i + 1}: unknown key {str(key)[:40]!r}")
            continue
        if key in seen:
            continue
        seen.add(key)
        reason = a.get("reason") if isinstance(a, dict) else None
        out.append({"key": key, "reason": reason.strip()[:300] if isinstance(reason, str) and reason.strip() else None})
    summary = data.get("summary")
    return (summary.strip()[:400] if isinstance(summary, str) else ""), out[: agent_guard.MAX_ASSETS_PER_RUN], problems


async def plan_campaign(campaign: dict, strategy: dict, override: list[str] | None = None) -> dict:
    """Return {summary, items, source, warning}. source: user | ai | rules | fallback."""
    if override:
        return {"summary": "Assets chosen by you.", "items": _items(override), "source": "user", "warning": None}
    s = get_settings()
    fallback_keys = default_keys(campaign)
    rules_summary = (f"Rule-based plan for a {campaign['platform']} campaign with the objective "
                     f"'{campaign['objective']}'.")
    if s.llm_provider == "mock":
        return {"summary": rules_summary, "items": _items(fallback_keys), "source": "rules", "warning": None}
    agent_guard.require("llm.generate")
    fn = llm.PROVIDERS.get(s.llm_provider)
    warning = None
    if fn:
        for attempt in range(2):
            try:
                raw = await fn(SYSTEM_PROMPT, build_prompt(campaign, strategy), 2000)
            except Exception as e:  # LLMError, network, auth...
                warning = f"The AI planner was unavailable ({str(e)[:120]}); a rule-based plan was used."
                break
            summary, picked, problems = parse_plan(raw)
            if picked:
                return {"summary": summary or "Plan created by the AI planner.",
                        "items": _items([p["key"] for p in picked], {p["key"]: p["reason"] for p in picked}),
                        "source": "ai", "warning": None}
            log.warning("planner attempt %d rejected: %s", attempt + 1, problems)
            warning = "The AI planner returned an unusable plan; a rule-based plan was used."
    else:
        warning = f"Unknown LLM_PROVIDER '{s.llm_provider}'; a rule-based plan was used."
    return {"summary": rules_summary, "items": _items(fallback_keys), "source": "fallback", "warning": warning}
