"""Structured prompt that converts raw campaign input into a marketing STRATEGY.

Phase 1 deliberately does not write posts/ads. It produces a strategy object that
later phases (content generation, optimisation) consume.
"""
import json

from schemas import CampaignInput

SYSTEM_PROMPT = """You are a senior marketing strategist at a top digital agency.
You turn a short product brief into a precise, actionable marketing STRATEGY.

Rules:
- Output ONLY one valid JSON object. No markdown fences, no commentary.
- Do NOT write final ad copy, posts or captions. Produce strategy only.
- Ground every point in the product details provided. Never invent features,
  prices, statistics or awards that are not in the brief.
- Tailor everything to the chosen platform, objective and tone.
- Write all string values in the requested output language.
- Keep JSON keys exactly as in the schema (keys stay in English).
"""

JSON_SCHEMA_HINT = {
    "campaign_idea": {"title": "str", "concept": "str (2-3 sentences)", "hook": "str (one-line big idea)"},
    "target_audience": {
        "summary": "str",
        "demographics": ["str (3-5)"],
        "psychographics": ["str (3-5)"],
        "pain_points": ["str (3-5)"],
    },
    "key_selling_points": [{"point": "str", "benefit": "str (customer benefit)"}],
    "content_tone": {
        "voice": "str",
        "style_guidelines": ["str (3-5)"],
        "words_to_use": ["str (5-8)"],
        "words_to_avoid": ["str (3-6)"],
    },
    "call_to_action": {"primary": "str", "alternatives": ["str (2-3)"]},
    "suggested_content_types": [
        {"type": "str (format for the platform)", "description": "str", "why_it_works": "str"}
    ],
    "success_metrics": ["str (3-5 KPIs matching the objective)"],
}


def build_user_prompt(data: CampaignInput) -> str:
    brief = {
        "product_name": data.product_name,
        "product_description": data.product_description,
        "target_audience": data.target_audience,
        "marketing_platform": data.platform.value,
        "campaign_objective": data.objective.value,
        "tone": data.tone.value,
        "output_language": data.language,
    }
    return (
        "CAMPAIGN BRIEF:\n"
        f"{json.dumps(brief, ensure_ascii=False, indent=2)}\n\n"
        "Return a marketing strategy as JSON matching exactly this shape "
        "(provide 4-6 key_selling_points and 4-6 suggested_content_types):\n"
        f"{json.dumps(JSON_SCHEMA_HINT, indent=2)}"
    )
