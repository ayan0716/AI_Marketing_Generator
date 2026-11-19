"""Phase 3 - image workflow service: concept-prompt generation, rendering, revision (Steps 1-4, 6, 8, 9)."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError

import image_providers as ip
import llm
import storage
from config import get_settings
from image_prompts import (
    REVISE_SYSTEM, STYLES, SYSTEM_PROMPT, build_concept_prompt, build_final_prompt,
    build_revise_prompt, fallback_revision,
)
from image_schemas import FORMAT_SPECS, CreativeFormat, ImageConcept

log = logging.getLogger("creative")
MAX_ATTEMPTS = 3
MAX_VERSIONS = 8
_gates: dict = {}

def _gate() -> asyncio.Semaphore:
    """At most 2 image requests in flight (provider rate limits). One semaphore per event loop."""
    loop = asyncio.get_running_loop()
    if loop not in _gates:
        _gates.clear()
        _gates[loop] = asyncio.Semaphore(2)
    return _gates[loop]

class PromptError(Exception):
    """No usable image concepts could be produced."""

class RunState:
    """Shared by all renders of one request: after a fatal error (bad key, no quota) stop calling the API."""
    def __init__(self):
        self.fatal: ip.ImageError | None = None

def _short(e: ValidationError, limit: int = 3) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:limit])

def parse_concepts(raw: str) -> tuple[list[dict], list[str]]:
    try:
        data = llm._extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        return [], ["reply was not valid JSON"]
    if isinstance(data, list):
        data = {"concepts": data}
    items = data.get("concepts") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        return [], ["JSON has no non-empty 'concepts' array"]
    ok, problems = [], []
    for i, item in enumerate(items):
        try:
            ok.append(ImageConcept.model_validate(item).model_dump())
        except ValidationError as e:
            problems.append(f"concept {i + 1}: {_short(e)}")
    return ok, problems

def _mock_concepts(fmt: CreativeFormat, campaign: dict, strategy: dict, count: int, start: int, has_product: bool) -> list[dict]:
    spec = FORMAT_SPECS[fmt]
    name = campaign["product_name"]
    desc = campaign.get("product_description", "")[:140]
    hook = strategy.get("campaign_idea", {}).get("hook", f"Meet {name}")
    palettes = [["white", "soft blue", "silver"], ["warm peach", "sage green", "cream"], ["sunny yellow", "coral", "navy"],
                ["deep navy", "teal glow", "amber"], ["ivory", "stone grey", "charcoal"]]
    out = []
    for i in range(count):
        k = (start + i) % len(STYLES)
        label, look = STYLES[k]
        product = (f"The supplied product photo of {name} is the hero, centered and unaltered." if has_product
                   else f"{name} shown as the hero product, large and clearly recognisable.")
        out.append({
            "name": f"{label}: {name}", "style_label": label,
            "concept_summary": f"{label} take on {name} for {spec['platform']}, built around: {hook}",
            "visual_style": look, "composition": spec["composition"][:290],
            "background": ["seamless light studio backdrop", "bright everyday indoor scene with natural window light",
                           "flat colour blocks with diagonal shapes", "dark atmospheric gradient with soft glow",
                           "calm off-white wall with soft shadow"][k],
            "lighting": ["soft diffused studio light", "warm natural daylight", "even bright flat lighting",
                         "dramatic rim light", "gentle window light"][k],
            "color_palette": palettes[k], "product_placement": product, "mood": ["clean", "warm", "energetic", "dramatic", "calm"][k],
            "text_overlay": hook[:60],
            "image_prompt": (f"{look.capitalize()}. Hero subject: {name} - {desc}. {product} "
                             f"Designed for {spec['platform']} ({spec['aspect']}), audience: {spec['audience']}. "
                             f"Palette: {', '.join(palettes[k])}. Premium advertising quality, sharp focus, no text."),
            "negative_prompt": "clutter, distorted product, extra text, watermark",
        })
    return [ImageConcept.model_validate(c).model_dump() for c in out]

async def generate_concepts(fmt, campaign, strategy, count, has_product, copy_hint=None, avoid=None, start_style=0):
    """Return (concepts, warnings). Invalid concepts are dropped and re-requested (like Phase 2 content)."""
    s = get_settings()
    if s.llm_provider == "mock":
        cs = _mock_concepts(fmt, campaign, strategy, count, start_style, has_product)
        for c in cs:
            c["id"] = uuid.uuid4().hex[:8]
        return cs, []
    fn = llm.PROVIDERS.get(s.llm_provider)
    if not fn:
        raise PromptError(f"Unknown LLM_PROVIDER '{s.llm_provider}'.")
    got, repair, problems = [], None, []
    for _ in range(MAX_ATTEMPTS):
        missing = count - len(got)
        if missing <= 0:
            break
        prompt = build_concept_prompt(fmt, campaign, strategy, missing, has_product, copy_hint,
                                      avoid=(avoid or []) + [c["image_prompt"][:140] for c in got],
                                      start_style=start_style + len(got), repair_note=repair)
        try:
            raw = await fn(SYSTEM_PROMPT, prompt, 6000)
        except llm.LLMError as e:
            raise PromptError(str(e)) from e
        except Exception as e:
            raise PromptError(f"{s.llm_provider} request failed: {e}") from e
        valid, problems = parse_concepts(raw)
        got.extend(valid[:missing])
        if problems:
            log.warning("%s concept problems: %s", fmt.value, problems)
            repair = " | ".join(problems)[:400]
        elif len(got) < count:
            repair = f"you returned {len(valid)} concept(s) but {missing} were required"
    if not got:
        raise PromptError(f"The AI returned invalid image prompts for {FORMAT_SPECS[fmt]['label']} "
                          f"({'; '.join(problems) or 'empty reply'}). Please try again.")
    warnings = [f"Only {len(got)} of {count} concepts were valid for {FORMAT_SPECS[fmt]['label']}."] if len(got) < count else []
    for c in got:
        c["id"] = uuid.uuid4().hex[:8]
    return got, warnings

async def revise_prompt(fmt, current_prompt: str, instructions: str, category: str) -> str:
    """Step 8: rewrite the image prompt with the user's modification. Never fails the request: falls back to appending."""
    s = get_settings()
    fallback = fallback_revision(current_prompt, instructions, category)
    if s.llm_provider == "mock" or s.llm_provider not in llm.PROVIDERS:
        return fallback
    try:
        raw = await llm.PROVIDERS[s.llm_provider](REVISE_SYSTEM, build_revise_prompt(fmt, current_prompt, instructions, category), 2000)
        data = llm._extract_json(raw)
        new = str(data.get("image_prompt", "")).strip()
        if 60 <= len(new) <= 1800:
            return new
    except Exception as e:
        log.warning("prompt revision fell back to append: %s", e)
    return fallback

async def render_version(fmt, campaign_id: str, concept: dict, image_prompt: str, product, state: RunState,
                         instruction: str | None = None) -> dict:
    """Send the final prompt to the image API, store the file, return a version record. Raises ImageError."""
    spec = FORMAT_SPECS[fmt]
    final = build_final_prompt(fmt, concept, image_prompt, product is not None)
    async with _gate():
        if state.fatal:
            raise state.fatal
        try:
            gen = await ip.generate_image(final, spec, product)
        except ip.ImageError as e:
            if e.kind in ip.FATAL_KINDS:
                state.fatal = e
            raise
        except Exception as e:  # a provider bug must never crash the whole batch
            log.exception("unexpected image provider failure")
            raise ip.ImageError("server", f"Unexpected image generation failure: {e.__class__.__name__}") from e
    vid = uuid.uuid4().hex[:8]
    rel = storage.save_bytes(f"creatives/{campaign_id}", f"{vid}.jpg", gen.data)
    return {"id": vid, "file": rel, "width": gen.width, "height": gen.height, "prompt": final,
            "instruction": instruction, "provider": gen.provider, "model": gen.model,
            "used_product": product is not None, "created_at": datetime.now(timezone.utc)}

async def render_concept(fmt, campaign_id: str, concept: dict, product, state: RunState) -> dict:
    """Render a brand-new concept; a failure is stored on the concept (so the UI can offer Retry) instead of raised."""
    concept = {**concept, "versions": [], "current_version": None, "status": "failed", "error": None}
    try:
        v = await render_version(fmt, campaign_id, concept, concept["image_prompt"], product, state)
        concept.update(versions=[v], current_version=v["id"], status="ready")
    except ip.ImageError as e:
        concept["error"] = e.to_dict()
    return concept
