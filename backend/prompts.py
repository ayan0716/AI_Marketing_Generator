"""Structured prompt that converts raw campaign input into a marketing STRATEGY.

Phase 1 deliberately does not write posts/ads. It produces a strategy object that
later phases (content generation, optimisation) consume.

Phase 5 changes (found by evaluating 6 industries x several audiences/objectives/platforms, see docs/EVALUATION.md):
  * rules against generic filler, invented statistics and repeated points
  * an INDUSTRY lens detected from the brief (e-commerce, education, restaurant, software, fashion, real estate)
  * explicit guidance per OBJECTIVE and per PLATFORM so KPIs and content formats actually fit the campaign
  * the JSON schema is unchanged, so every other phase keeps working
"""
import json
import re

from schemas import CampaignInput

SYSTEM_PROMPT = """You are a senior marketing strategist at a top digital agency.
You turn a short product brief into a precise, actionable marketing STRATEGY.

Rules:
- Output ONLY one valid JSON object. No markdown fences, no commentary.
- Do NOT write final ad copy, posts or captions. Produce strategy only.
- Ground every point in the product details provided. Never invent features, prices, discounts,
  statistics, percentages, awards, customer numbers or testimonials that are not in the brief.
- Be SPECIFIC. Name the real product, its real features and the real situation of this audience.
  Avoid filler such as "game-changer", "revolutionary", "cutting-edge", "unlock the power", "next level".
- Every list item must add something new: no two selling points, content types or metrics may express the same idea.
- Selling points are different ANGLES (e.g. a functional benefit, an emotional benefit, a proof/trust point,
  a convenience point), each with a concrete customer benefit.
- The campaign objective decides the call to action and the KPIs; the platform decides the content formats.
- words_to_use and words_to_avoid must never overlap.
- The primary call to action is a short imperative (2-6 words) that fits the objective.
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

# ---------------------------------------------------------------- industry lens (keyword detection, no extra API call)
INDUSTRY_PLAYBOOKS = {
    "e-commerce": (
        ("shop", "store", "ecommerce", "e-commerce", "bottle", "gadget", "accessor", "shipping", "delivery", "water bottle"),
        "Online retail: lead with a concrete product benefit and use case, show it in use, reduce purchase risk "
        "(returns, delivery, reviews ONLY if given in the brief), and keep one clear buying step.",
    ),
    "education": (
        ("course", "learn", "student", "school", "academy", "tutor", "bootcamp", "training", "teach", "exam", "university"),
        "Education: sell the OUTCOME (skill, grade, career step), address time and trust concerns, show the learning "
        "path and who teaches. Never promise guaranteed jobs or grades.",
    ),
    "restaurant": (
        ("restaurant", "cafe", "café", "coffee", "menu", "dish", "chef", "pizza", "burger", "bakery", "dining", "food", "brunch"),
        "Food & hospitality: sell the sensory experience and the occasion (date night, family, lunch break), use "
        "appetite-led visuals, local relevance and a reservation / order action.",
    ),
    "software": (
        ("software", "saas", "app ", "platform", "api", "dashboard", "automation", "workflow", "ai-powered", "tool for", "developer"),
        "Software / SaaS: lead with the problem and the time or money it saves, show a concrete workflow, address "
        "switching effort and trust (security, integrations only if in the brief), and use a trial / demo CTA.",
    ),
    "fashion": (
        ("clothing", "fashion", "apparel", "wear", "dress", "sneaker", "jacket", "streetwear", "collection", "fabric", "outfit"),
        "Fashion: sell identity and occasion, not only the garment; use lookbook-style content, fit, fabric and "
        "styling ideas, and seasonal or drop-based urgency only when the brief supports it.",
    ),
    "real estate": (
        ("real estate", "property", "apartment", "villa", "home for sale", "listing", "realtor", "housing", "condo", "mortgage", "rent"),
        "Real estate: sell the lifestyle, location and a practical next step (viewing, brochure); stay factual about "
        "size, price and amenities and never invent figures. Respect fair-housing language: no discriminatory targeting.",
    ),
}

OBJECTIVE_GUIDE = {
    "Brand Awareness": "Optimise for reach and recall: memorable hook, shareable formats. KPIs: reach, impressions, video views, follower growth.",
    "Lead Generation": "Optimise for qualified contacts: a clear offer in exchange for details. KPIs: leads, cost per lead, form completion rate.",
    "Sales / Conversions": "Optimise for purchases: benefits, proof and a low-friction buying step. KPIs: conversion rate, ROAS, cost per purchase.",
    "Engagement": "Optimise for interaction: questions, polls, user participation. KPIs: engagement rate, comments, shares, saves.",
    "Product Launch": "Optimise for a launch arc: tease, reveal, first-use proof. KPIs: launch-week reach, waitlist or pre-orders, first sales.",
    "Customer Retention": "Optimise for existing customers: loyalty, onboarding, advanced use. KPIs: repeat purchase rate, churn, NPS, re-engagement.",
}

PLATFORM_GUIDE = {
    "Instagram": "Visual-first: Reels, carousels, Stories; hooks in the first line; 5-10 relevant hashtags.",
    "Facebook": "Community and ads: longer captions are fine, groups, video and clear offers.",
    "LinkedIn": "Professional: insight-led posts, thought leadership, case-study style, no slang.",
    "X (Twitter)": "Short, punchy, conversational; threads and timely hooks; 1-2 hashtags.",
    "TikTok": "Native vertical video, trend-aware, first 2 seconds decide; casual, authentic voice.",
    "YouTube": "Search-driven: title and thumbnail promise, tutorials and demos, strong first 15 seconds.",
    "Email": "Subject line and preview text decide opens; one goal per email; segment-aware.",
    "Google Ads": "Intent-driven search: keyword-matched headlines, tight character limits, strong offer and CTA.",
    "Website / Blog": "SEO and depth: a search intent per article, helpful structure, internal calls to action.",
}


def detect_industry(data: CampaignInput) -> str | None:
    """Best-matching industry playbook by keyword score (None when nothing matches clearly)."""
    # product name + description only: the audience ("students", "families") describes who buys, not what is sold
    text = f" {data.product_name} {data.product_description} ".lower()
    best, score = None, 0
    for name, (keywords, _) in INDUSTRY_PLAYBOOKS.items():
        s = sum(1 for k in keywords if re.search(r"(?<!\w)" + re.escape(k), text))
        if s > score:
            best, score = name, s
    return best if score >= 1 else None


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
    guidance = [
        f"- Objective ({data.objective.value}): {OBJECTIVE_GUIDE.get(data.objective.value, '')}",
        f"- Platform ({data.platform.value}): {PLATFORM_GUIDE.get(data.platform.value, '')}",
    ]
    industry = detect_industry(data)
    if industry:
        guidance.insert(0, f"- Industry ({industry}): {INDUSTRY_PLAYBOOKS[industry][1]}")
    return (
        "CAMPAIGN BRIEF:\n"
        f"{json.dumps(brief, ensure_ascii=False, indent=2)}\n\n"
        "STRATEGIC GUIDANCE (apply it, do not quote it):\n"
        + "\n".join(guidance)
        + "\n\n"
        "Return a marketing strategy as JSON matching exactly this shape "
        "(provide 4-6 key_selling_points and 4-6 suggested_content_types):\n"
        f"{json.dumps(JSON_SCHEMA_HINT, indent=2)}"
    )