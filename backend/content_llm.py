"""Phase 2 - content generation service with validation, partial-result handling and retry (Step 8)."""

import json
import logging
import uuid

from pydantic import ValidationError

import llm
from config import get_settings
from content_prompts import ANGLES, SYSTEM_PROMPT, build_content_prompt
from content_schemas import PLATFORM_MODELS, ContentPlatform

log = logging.getLogger("content")
MAX_ATTEMPTS = 3


class ContentError(Exception):
    """Raised when no usable content could be produced for a platform."""


def _short_errors(e: ValidationError, limit: int = 4) -> str:
    items = []
    for err in e.errors()[:limit]:
        loc = ".".join(str(x) for x in err["loc"])
        items.append(f"{loc}: {err['msg']}")
    return "; ".join(items)


def parse_variations(platform: ContentPlatform, raw: str) -> tuple[list[dict], list[str]]:
    """Return (valid_variations, problems). Never raises on bad model output."""
    model = PLATFORM_MODELS[platform]
    problems: list[str] = []
    try:
        data = llm._extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        return [], ["reply was not valid JSON"]
    if isinstance(data, list):  # model returned a bare array
        data = {"variations": data}
    items = data.get("variations") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return [], ["JSON has no non-empty 'variations' array"]
    valid: list[dict] = []
    for i, item in enumerate(items):
        try:
            valid.append(model.model_validate(item).model_dump())
        except ValidationError as e:
            problems.append(f"variation {i + 1}: {_short_errors(e)}")
    return valid, problems


def _mock_variations(platform: ContentPlatform, campaign: dict, strategy: dict, count: int, offset: int) -> list[dict]:
    """Deterministic offline content so the whole app works without an API key."""
    name = campaign["product_name"]
    pts = [p["point"] for p in strategy.get("key_selling_points", [])] or ["Quality you can feel"]
    benefits = [p["benefit"] for p in strategy.get("key_selling_points", [])] or ["Makes life easier"]
    cta = strategy.get("call_to_action", {}).get("primary", "Learn more")
    alts = strategy.get("call_to_action", {}).get("alternatives", []) or [cta]
    hook = strategy.get("campaign_idea", {}).get("hook", f"Meet {name}.")
    audience = (campaign.get("target_audience") or "you").split(",")[0][:90]
    pain = (strategy.get("target_audience", {}).get("pain_points") or ["Too many options"])
    slug = "".join(ch for ch in name.title() if ch.isalnum()) or "Brand"
    tags = [slug, "NewArrival", "MustHave", "SmartChoice", "DailyEssentials", "ShopSmart", "TrendingNow"]
    openers = [
        lambda: f"Tired of this? {pain[0]}.",
        lambda: f"Here is why {name} is different.",
        lambda: f"Real people. Real results with {name}.",
        lambda: f"What if {benefits[0].lower().rstrip('.')}?",
        lambda: f"Ready for {name}? Now is the time.",
    ]
    out: list[dict] = []
    for i in range(count):
        k = (offset + i) % len(ANGLES)
        angle, opener = ANGLES[k], openers[k]()
        j = offset + i
        point, benefit, c = pts[j % len(pts)], benefits[j % len(benefits)], alts[j % len(alts)] if j else cta
        if platform == ContentPlatform.instagram:
            out.append({
                "angle": angle, "hook": opener,
                "main_message": f"{name} is made for {audience}. {point}: {benefit.rstrip('.')}. {hook}",
                "call_to_action": f"{c} - link in bio.", "hashtags": tags[: 6 + i % 3],
            })
        elif platform == ContentPlatform.instagram_story:
            out.append({
                "angle": angle, "hook": opener,
                "frames": [
                    {"visual": f"Close-up of {name} in a bright everyday scene", "text_overlay": opener[:100], "interaction": "Poll: Yes / Not yet"},
                    {"visual": f"Quick demo showing: {point}", "text_overlay": point[:100], "interaction": ""},
                    {"visual": "Happy customer moment, handheld, natural light", "text_overlay": benefit[:100], "interaction": "Emoji slider"},
                    {"visual": f"Product shot with brand colours and logo", "text_overlay": c[:100], "interaction": "Link sticker"},
                ],
                "call_to_action": f"{c} - tap the link sticker.",
            })
        elif platform == ContentPlatform.linkedin:
            out.append({
                "angle": angle,
                "introduction": f"{opener} For {audience}, that question matters more every quarter.",
                "value_proposition": f"{name} delivers {benefit.lower().rstrip('.')} - without the usual compromise.",
                "main_content": f"{hook}\n\nWhat sets it apart: {point}.\n\nWhy it matters: {benefit.rstrip('.')}.\n\nWe built this approach around what {audience} told us they need.",
                "call_to_action": f"{c} - and tell us your experience in the comments.",
                "hashtags": [slug, "Innovation", "Growth", "Productivity"][: 3 + i % 2],
            })
        elif platform == ContentPlatform.facebook:
            out.append({
                "angle": angle, "headline": (point if len(point) <= 38 else point[:35] + "...") or name,
                "primary_text": f"{opener} {name} helps {audience}: {benefit.rstrip('.')}.",
                "call_to_action": c[:40],
                "short_description": f"{name} - {point}"[:110] if i % 2 == 0 else "",
            })
        elif platform == ContentPlatform.youtube:
            out.append({
                "angle": angle, "video_title": f"{name}: {point} ({angle})"[:100],
                "hook": f"{opener} In the next minute I will show you exactly how {name} changes that.",
                "description": f"{hook}\n\nIn this video: how {name} works, who it is for ({audience}), and why {benefit.lower().rstrip('.')}.\n\n{c}!",
                "call_to_action": f"{c} - and subscribe for more.",
                "thumbnail_concept": f"Product close-up on a bold contrasting background, surprised face on the right, overlay text '{name[:18]}?'",
            })
    return out


async def generate_variations(
    platform: ContentPlatform,
    campaign: dict,
    strategy: dict,
    count: int = 3,
    avoid: list[str] | None = None,
    angle_offset: int = 0,
) -> tuple[list[dict], str, str, list[str]]:
    """Generate `count` validated variations.

    Returns (variations, provider, model, warnings). Invalid / incomplete items are dropped and
    re-requested up to MAX_ATTEMPTS. If at least one valid variation exists we return it with a
    warning; if none, ContentError is raised with a readable message.
    """
    s = get_settings()
    if s.llm_provider == "mock":
        mocks = _mock_variations(platform, campaign, strategy, count, angle_offset)
        model = PLATFORM_MODELS[platform]
        mocks = [model.model_validate(m).model_dump() for m in mocks]  # mock obeys the same schema
        for m in mocks:
            m["id"] = uuid.uuid4().hex[:8]
        return mocks, "mock", "mock", []

    fn = llm.PROVIDERS.get(s.llm_provider)
    if not fn:
        raise ContentError(f"Unknown LLM_PROVIDER '{s.llm_provider}'.")

    collected: list[dict] = []
    repair: str | None = None
    last_problems: list[str] = []
    for attempt in range(MAX_ATTEMPTS):
        missing = count - len(collected)
        if missing <= 0:
            break
        prompt = build_content_prompt(
            platform, campaign, strategy, missing,
            avoid=(avoid or []) + [json.dumps(c, ensure_ascii=False)[:140] for c in collected],
            start_angle=angle_offset + len(collected), repair_note=repair,
        )
        try:
            raw = await fn(SYSTEM_PROMPT, prompt, 6000)
        except llm.LLMError as e:
            raise ContentError(str(e)) from e  # auth / config problems: retrying will not help
        except Exception as e:
            raise ContentError(f"{s.llm_provider} request failed: {e}") from e
        valid, problems = parse_variations(platform, raw)
        collected.extend(valid[:missing])
        last_problems = problems
        if problems:
            log.warning("%s attempt %d problems: %s", platform.value, attempt + 1, problems)
            repair = " | ".join(problems)[:400]
        elif len(collected) < count:
            repair = f"you returned {len(valid)} variation(s) but {missing} were required"

    if not collected:
        raise ContentError(
            f"The AI returned invalid {platform.value} content ({'; '.join(last_problems) or 'empty reply'}). "
            "Please press Regenerate."
        )
    warnings = []
    if len(collected) < count:
        warnings.append(f"Only {len(collected)} of {count} variations were valid; press Regenerate for more.")
    for v in collected:
        v["id"] = uuid.uuid4().hex[:8]
    return collected, s.llm_provider, llm.active_model(), warnings
