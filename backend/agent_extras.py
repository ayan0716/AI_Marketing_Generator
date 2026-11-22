"""Phase 4 - generation of the two new asset types (reel concept, promotional caption).
Same pattern as Phase 2: structured prompt -> JSON -> Pydantic validation -> repair retry -> clean error."""
import json
import logging

from pydantic import ValidationError

import agent_guard
import llm
from agent_schemas import EXTRA_MODELS
from config import get_settings

log = logging.getLogger("agent.extras")
MAX_ATTEMPTS = 3


class ExtraError(Exception):
    """No usable asset could be produced."""


SYSTEM_PROMPT = """You are a senior short-form video strategist and social copywriter.
You turn an approved marketing STRATEGY into one ready-to-use asset.
Rules:
- Output ONLY one valid JSON object. No markdown fences, no commentary.
- Follow the strategy: its tone, key selling points, words_to_use and call to action. Never use words_to_avoid.
- Ground every claim in the brief. Never invent prices, statistics, awards, testimonials or features.
- Write all string values in the requested output language (JSON keys stay in English), except
  cover_image_prompt which is written in English for an image model and must not ask for rendered text.
- Respect the character limits in the shape. Hashtags are plain words without spaces.
"""

_SPECS = {
    "instagram_reel": {
        "name": "short-video (Reel) concept",
        "brief": ("Create ONE Reel / short-video concept of 15-30 seconds. The hook must work in the first 2 seconds. "
                  "Give 3-6 scenes, each with what is shown, very short on-screen text and a duration in seconds. "
                  "Suggest the audio style (not a copyrighted song title), the CTA, a caption and hashtags, and a "
                  "cover_image_prompt describing the cover frame for an image model."),
        "shape": {
            "angle": "str (2-4 words)", "title": "str (max 100 chars)", "hook": "str (max 200 chars)",
            "scenes": [{"visual": "str (max 300 chars)", "on_screen_text": "str (max 120 chars)", "seconds": "int 1-30"}],
            "audio_suggestion": "str (max 200 chars)", "call_to_action": "str (max 150 chars)",
            "caption": "str (max 800 chars)", "hashtags": ["str (5-8 tags)"],
            "cover_image_prompt": "str (English, 30-600 chars, no text in the image)",
        },
    },
    "promo_caption": {
        "name": "promotional caption",
        "brief": ("Write ONE short promotional caption that can be reused across channels: a punchy headline, a "
                  "benefit-led caption, an OPTIONAL offer line (only if the brief supports an offer, otherwise ''), "
                  "one clear call to action and a few hashtags."),
        "shape": {
            "angle": "str", "headline": "str (max 80 chars)", "caption": "str (max 600 chars)",
            "offer_line": "str (optional, max 120 chars, '' if none)", "call_to_action": "str (max 100 chars)",
            "hashtags": ["str (3-6 tags)"],
        },
    },
}


def build_prompt(key: str, campaign: dict, strategy: dict, repair_note: str | None = None) -> str:
    spec = _SPECS[key]
    brief = {
        "product_name": campaign["product_name"],
        "product_description": campaign.get("product_description", ""),
        "campaign_platform": campaign["platform"],
        "campaign_objective": campaign["objective"],
        "tone": campaign["tone"],
        "output_language": campaign.get("language", "English"),
    }
    s = strategy
    view = {
        "campaign_idea": s.get("campaign_idea"),
        "audience_summary": s.get("target_audience", {}).get("summary"),
        "pain_points": s.get("target_audience", {}).get("pain_points"),
        "key_selling_points": s.get("key_selling_points"),
        "content_tone": s.get("content_tone"),
        "call_to_action": s.get("call_to_action"),
    }
    parts = [
        f"TASK: write one {spec['name']}.", spec["brief"],
        "CAMPAIGN BRIEF:\n" + json.dumps(brief, ensure_ascii=False, indent=2),
        "APPROVED MARKETING STRATEGY:\n" + json.dumps(view, ensure_ascii=False, indent=2),
    ]
    if repair_note:
        parts.append(f"YOUR PREVIOUS REPLY WAS REJECTED: {repair_note}\nFix this and return ONLY the JSON object.")
    parts.append("Return JSON in exactly this shape:\n" + json.dumps(spec["shape"], indent=2, ensure_ascii=False))
    return "\n\n".join(parts)


def parse_extra(key: str, raw: str) -> tuple[dict | None, str | None]:
    try:
        data = llm._extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        return None, "reply was not valid JSON"
    if isinstance(data, dict) and isinstance(data.get("variations"), list) and data["variations"]:
        data = data["variations"][0]  # tolerate the Phase 2 wrapper
    try:
        return EXTRA_MODELS[key].model_validate(data).model_dump(), None
    except ValidationError as e:
        return None, "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:4])
    except TypeError:
        return None, "reply was not a JSON object"


def _mock(key: str, campaign: dict, strategy: dict) -> dict:
    name = campaign["product_name"]
    pts = strategy.get("key_selling_points") or [{"point": "Quality you can feel", "benefit": "Makes life easier"}]
    p0, p1 = pts[0], pts[min(1, len(pts) - 1)]
    cta = strategy.get("call_to_action", {}).get("primary", "Learn more")
    hook = strategy.get("campaign_idea", {}).get("hook", f"Meet {name}.")
    slug = "".join(ch for ch in name.title() if ch.isalnum()) or "Brand"
    if key == "instagram_reel":
        return {
            "angle": "Problem to payoff", "title": f"{name} in 20 seconds", "hook": f"Stop scrolling: {hook}",
            "scenes": [
                {"visual": f"Fast close-up of {name} in a bright everyday setting", "on_screen_text": hook[:100], "seconds": 3},
                {"visual": f"Quick demo showing: {p0['point']}", "on_screen_text": p0["point"][:100], "seconds": 6},
                {"visual": "Happy customer moment, handheld, natural light", "on_screen_text": p1["benefit"][:100], "seconds": 6},
                {"visual": f"Product hero shot with brand colours", "on_screen_text": cta[:100], "seconds": 5},
            ],
            "audio_suggestion": "Upbeat, modern instrumental with a clear beat drop at the product reveal",
            "call_to_action": f"{cta} - link in bio.",
            "caption": f"{hook} {p0['benefit'].rstrip('.')}. {cta}!",
            "hashtags": [slug, "Reels", "MustHave", "NewArrival", "SmartChoice"],
            "cover_image_prompt": (f"Bright, bold cover frame for a short video: {name} as the hero product, centered, "
                                   "vertical 9:16 composition, high contrast, clean background, no text in the image."),
        }
    return {
        "angle": "Offer-led", "headline": f"{name}: {p0['point']}"[:80],
        "caption": f"{hook} {p0['benefit'].rstrip('.')} - and {p1['benefit'].lower().rstrip('.')}.",
        "offer_line": "", "call_to_action": cta[:100], "hashtags": [slug, "NewArrival", "ShopSmart"],
    }


async def generate_extra(key: str, campaign: dict, strategy: dict) -> tuple[dict, str, str]:
    """Return (data, provider, model). Raises ExtraError with a readable message."""
    s = get_settings()
    if s.llm_provider == "mock":
        data = EXTRA_MODELS[key].model_validate(_mock(key, campaign, strategy)).model_dump()
        return data, "mock", "mock"
    fn = llm.PROVIDERS.get(s.llm_provider)
    if not fn:
        raise ExtraError(f"Unknown LLM_PROVIDER '{s.llm_provider}'.")
    agent_guard.require("llm.generate")
    repair, last = None, "empty reply"
    for attempt in range(MAX_ATTEMPTS):
        try:
            raw = await fn(SYSTEM_PROMPT, build_prompt(key, campaign, strategy, repair), 4000)
        except llm.LLMError as e:
            raise ExtraError(str(e)) from e
        except Exception as e:
            raise ExtraError(f"{s.llm_provider} request failed: {e}") from e
        data, problem = parse_extra(key, raw)
        if data:
            return data, s.llm_provider, llm.active_model()
        last = problem or last
        log.warning("%s attempt %d rejected: %s", key, attempt + 1, problem)
        repair = (problem or "")[:400]
    raise ExtraError(f"The AI returned an invalid {_SPECS[key]['name']} ({last}). Please regenerate.")
