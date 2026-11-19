"""Phase 3 - converts strategy + product info into platform-specific image-generation prompts (Steps 1-2).

Two layers:
  1. The LLM acts as an art director and returns several structured visual CONCEPTS (style, composition,
     background, lighting, palette, product placement, image_prompt).
  2. build_final_prompt() appends the deterministic, platform-specific rules (aspect ratio, safe zones,
     audience, product-reference instruction, "no rendered text") so every format is shaped correctly even
     when the LLM forgets something.
"""

import json

from image_schemas import FORMAT_SPECS, CreativeFormat

SYSTEM_PROMPT = """You are a senior art director at a top digital advertising agency.
You turn an approved marketing STRATEGY and a product brief into detailed prompts for an AI image generator.
Rules:
- Output ONLY one valid JSON object. No markdown fences, no commentary.
- Return exactly the requested number of concepts. Each concept must be visually DIFFERENT
  (different style direction, background, composition and colour palette) - never minor rewordings.
- image_prompt is one rich paragraph written for an image model: subject, setting, composition, camera/angle,
  lighting, colour palette, materials, mood and style. Be concrete and visual, not abstract marketing talk.
- Ground everything in the brief. Never invent product features, logos, slogans, prices or people's identities.
- Do NOT ask the image model to render any text, letters, numbers, slogans or logos. Put the caption idea in
  text_overlay instead (it is added later outside the image).
- Tailor every concept to the target platform, audience, objective and tone provided.
- Visual descriptions are written in English (image models work best in English); text_overlay is written in
  the requested output language.
"""

# One style direction per concept so multiple concepts for the same campaign genuinely differ.
STYLES = [
    ("Studio hero", "clean professional studio product shot on a seamless backdrop, soft shadows, crisp detail"),
    ("Lifestyle in context", "natural lifestyle photograph of the product being used by the target audience in a real setting"),
    ("Bold graphic", "bold flat-colour graphic poster look with strong geometric shapes and high contrast"),
    ("Cinematic mood", "cinematic dramatic photograph with moody directional lighting, depth and atmosphere"),
    ("Minimal editorial", "minimal editorial layout with lots of negative space, refined palette and elegant simplicity"),
]

_SHAPE = {
    "name": "str (3-6 words, concept title)",
    "style_label": "str (2-3 words, e.g. 'Studio hero')",
    "concept_summary": "str (1-2 sentences describing the idea)",
    "visual_style": "str (photography / illustration / 3D / flat ... and finish)",
    "composition": "str (framing, subject position, negative space)",
    "background": "str (setting and backdrop)",
    "lighting": "str",
    "color_palette": ["str (2-5 colours, plain names)"],
    "product_placement": "str (where and how the product appears)",
    "mood": "str (2-4 words)",
    "text_overlay": "str (optional short caption idea in the output language, max 60 chars, '' if none)",
    "image_prompt": "str (one detailed paragraph, 60-1500 chars, the prompt sent to the image model)",
    "negative_prompt": "str (optional: things to avoid, e.g. clutter, extra text)",
}

def build_concept_prompt(
    fmt: CreativeFormat,
    campaign: dict,
    strategy: dict,
    count: int,
    has_product_image: bool,
    copy_hint: dict | None = None,
    avoid: list[str] | None = None,
    start_style: int = 0,
    repair_note: str | None = None,
) -> str:
    spec = FORMAT_SPECS[fmt]
    styles = [STYLES[(start_style + i) % len(STYLES)] for i in range(count)]
    brief = {
        "product_name": campaign["product_name"],
        "product_description": campaign.get("product_description", ""),
        "target_audience": campaign.get("target_audience", ""),
        "campaign_objective": campaign["objective"],
        "tone": campaign["tone"],
        "output_language": campaign.get("language", "English"),
    }
    s = strategy
    strategy_view = {
        "campaign_idea": s.get("campaign_idea"),
        "audience_summary": s.get("target_audience", {}).get("summary"),
        "audience_psychographics": s.get("target_audience", {}).get("psychographics"),
        "key_selling_points": s.get("key_selling_points"),
        "tone_of_voice": s.get("content_tone", {}).get("voice"),
        "call_to_action": s.get("call_to_action", {}).get("primary"),
    }
    platform = {
        "format": spec["label"],
        "platform": spec["platform"],
        "aspect_ratio": spec["aspect"],
        "final_size_px": f"{spec['width']}x{spec['height']}",
        "who_sees_it": spec["audience"],
        "composition_rules": spec["composition"],
    }
    parts = [
        f"TASK: write {count} different image concept(s) with ready-to-use image prompts for a {spec['label']}.",
        "TARGET PLATFORM FORMAT:\n" + json.dumps(platform, ensure_ascii=False, indent=2),
        "CAMPAIGN BRIEF:\n" + json.dumps(brief, ensure_ascii=False, indent=2),
        "APPROVED MARKETING STRATEGY:\n" + json.dumps(strategy_view, ensure_ascii=False, indent=2),
        "Use these style directions, one per concept, in this order:\n"
        + "\n".join(f"{i + 1}. {n} - {d}" for i, (n, d) in enumerate(styles)),
    ]
    if copy_hint:
        parts.append("APPROVED COPY FOR THIS PLATFORM (keep the visual consistent with it):\n"
                     + json.dumps(copy_hint, ensure_ascii=False, indent=2))
    if has_product_image:
        parts.append(
            "The customer supplied a PRODUCT PHOTO that will be passed to the image model as a reference. "
            "Describe how that exact product appears in the scene (placement, scale, angle). Do not redesign "
            "the product."
        )
    else:
        parts.append(
            f"No product photo was supplied: describe {campaign['product_name']} generically from the product "
            "description (shape, material, colours) without inventing branding."
        )
    if avoid:
        parts.append("These concepts already exist - make yours clearly different:\n- " + "\n- ".join(a[:140] for a in avoid))
    if repair_note:
        parts.append(f"YOUR PREVIOUS REPLY WAS REJECTED: {repair_note}\nFix this and return ONLY the JSON object.")
    parts.append(
        f"Return JSON in exactly this shape, with 'concepts' holding exactly {count} item(s):\n"
        + json.dumps({"concepts": [_SHAPE]}, indent=2, ensure_ascii=False)
    )
    return "\n\n".join(parts)

def build_final_prompt(fmt: CreativeFormat, concept: dict, image_prompt: str, with_product: bool) -> str:
    """The exact text sent to the image model: concept prompt + deterministic platform rules."""
    spec = FORMAT_SPECS[fmt]
    lines = [
        image_prompt.strip(),
        f"Format: {spec['label']} for {spec['platform']}, aspect ratio {spec['aspect']}. {spec['composition']}",
        f"Audience: {spec['audience']}.",
    ]
    if concept.get("color_palette"):
        lines.append("Colour palette: " + ", ".join(concept["color_palette"]) + ".")
    if with_product:
        lines.append(
            "Use the attached product photo as the hero product: keep its exact shape, proportions, colours and "
            "any printed branding unchanged, only place it naturally into the scene with correct lighting, "
            "shadows and reflections."
        )
    lines.append("Do not add any text, letters, numbers, captions, watermarks or invented logos to the image.")
    if concept.get("negative_prompt"):
        lines.append("Avoid: " + concept["negative_prompt"].strip())
    return "\n".join(lines)

# ---------- Step 8: regenerate with modified instructions ----------
CATEGORY_HINTS = {
    "background": "Change the background / setting as requested.",
    "style": "Change the visual style / rendering as requested.",
    "composition": "Change the composition / framing / layout as requested.",
    "tone": "Change the marketing tone and mood as requested.",
    "other": "Apply the requested change.",
}

REVISE_SYSTEM = """You are a senior art director editing an image-generation prompt.
Rewrite the given prompt so it applies the requested change while keeping everything else
(product, platform format, composition rules, no-text rule) intact.
Output ONLY one valid JSON object: {"image_prompt": "<the full revised prompt, 60-1500 characters>"}."""

def build_revise_prompt(fmt: CreativeFormat, current_prompt: str, instructions: str, category: str) -> str:
    spec = FORMAT_SPECS[fmt]
    return (
        f"PLATFORM FORMAT: {spec['label']} ({spec['aspect']}).\n\nCURRENT PROMPT:\n{current_prompt}\n\n"
        f"CHANGE REQUESTED ({category}): {instructions}\n{CATEGORY_HINTS.get(category, '')}\n\n"
        'Return {"image_prompt": "..."} only.'
    )

def fallback_revision(current_prompt: str, instructions: str, category: str) -> str:
    """Deterministic revision used in mock mode or if the LLM rewrite fails."""
    base = current_prompt.split("\n\nREVISION", 1)[0].strip()
    return (
        f"{base}\n\nREVISION ({category}): {instructions.strip().rstrip('.')}. "
        "Apply this change while keeping the product, the platform composition rules and the brand look consistent."
    )
