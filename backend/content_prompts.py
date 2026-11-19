"""Phase 2 - one dedicated prompt per platform (Step 1).

Shared rules live in SYSTEM_PROMPT; each platform adds its own writing brief and
its own JSON shape. All prompts are built from the Phase 1 strategy object.
"""

import json

from content_schemas import ContentPlatform

SYSTEM_PROMPT = """You are a senior social-media copywriter at a top digital agency.
You turn an approved marketing STRATEGY into ready-to-publish, platform-specific content.
Rules:
- Output ONLY one valid JSON object. No markdown fences, no commentary.
- Return exactly the requested number of variations; each must use a clearly DIFFERENT angle
  (for example problem-first, benefit-first, story/social-proof, question-led, offer-led).
- Follow the strategy: use its tone, key selling points, words_to_use, and call to action.
  Never use anything listed in words_to_avoid.
- Ground every claim in the brief. Never invent prices, statistics, awards, testimonials or features.
- Write all string values in the requested output language (JSON keys stay in English).
- Respect the character limits given in the schema hints. Hashtags are plain words without spaces.
"""

# ---- per platform: writing brief + JSON shape for ONE variation ----
_PLATFORM_BRIEFS: dict[ContentPlatform, dict] = {
    ContentPlatform.instagram: {
        "name": "Instagram feed caption",
        "brief": (
            "Write scroll-stopping Instagram captions. The hook is the first line (what shows before 'more'): "
            "short, curious or bold. Then a main message that is conversational and benefit-led, "
            "then ONE clear call-to-action, then relevant hashtags (mix 2-3 broad and 4-6 niche tags)."
        ),
        "shape": {
            "angle": "str (2-4 words naming this variation's approach)",
            "hook": "str (max 150 chars, first line)",
            "main_message": "str (2-5 short sentences, max 1500 chars, emojis allowed sparingly)",
            "call_to_action": "str (max 150 chars)",
            "hashtags": ["str (6-10 tags, without spaces)"],
        },
    },
    ContentPlatform.instagram_story: {
        "name": "Instagram Story sequence",
        "brief": (
            "Write a 3-5 frame Instagram Story sequence. Frame 1 must grab attention in under 2 seconds. "
            "For each frame describe the visual, give very short on-screen text, and optionally an interactive "
            "sticker (poll, quiz, question box, link sticker). The last frame carries the call-to-action."
        ),
        "shape": {
            "angle": "str",
            "hook": "str (max 150 chars, text of frame 1)",
            "frames": [
                {
                    "visual": "str (what is shown, max 300 chars)",
                    "text_overlay": "str (max 120 chars)",
                    "interaction": "str (optional sticker idea, '' if none)",
                }
            ],
            "call_to_action": "str (max 150 chars)",
        },
    },
    ContentPlatform.linkedin: {
        "name": "LinkedIn post",
        "brief": (
            "Write professional but human LinkedIn posts: a strong professional introduction (the first two lines "
            "decide whether people click 'see more'), a crisp value proposition, main content with insight or a "
            "mini-story (short paragraphs, line breaks allowed), a call-to-action inviting a comment or visit, "
            "and 3-5 industry hashtags. No clickbait, no emoji spam."
        ),
        "shape": {
            "angle": "str",
            "introduction": "str (max 400 chars)",
            "value_proposition": "str (1-2 sentences, max 500 chars)",
            "main_content": "str (max 2000 chars, short paragraphs separated by \\n\\n)",
            "call_to_action": "str (max 200 chars)",
            "hashtags": ["str (3-5 tags)"],
        },
    },
    ContentPlatform.facebook: {
        "name": "Facebook ad copy",
        "brief": (
            "Write Facebook advertising copy. Headline: punchy, ideally under 40 characters. Primary text: the "
            "persuasive body shown above the image (benefit first, 1-3 short sentences, ideally under 125 characters "
            "before the fold but max 700 total). call_to_action should read like a Facebook button label "
            "(e.g. 'Shop Now', 'Learn More', 'Sign Up'). short_description is an OPTIONAL one-line link description "
            "(max 120 chars, use an empty string if not needed)."
        ),
        "shape": {
            "angle": "str",
            "headline": "str (max 80 chars, aim for 40)",
            "primary_text": "str (max 700 chars)",
            "call_to_action": "str (button label, max 60 chars)",
            "short_description": "str (optional, max 120 chars, '' allowed)",
        },
    },
    ContentPlatform.youtube: {
        "name": "YouTube video content",
        "brief": (
            "Write YouTube video packaging. video_title: searchable and clickable, max 100 characters, no all-caps "
            "spam. hook: the spoken first 5-10 seconds of the video. description: keyword-aware, first two lines "
            "summarise the value, then what viewers will see, then the call-to-action. thumbnail_concept: a concrete "
            "visual idea (subject, expression/composition, 3-5 word overlay text, colour contrast)."
        ),
        "shape": {
            "angle": "str",
            "video_title": "str (max 100 chars)",
            "description": "str (max 2500 chars)",
            "hook": "str (max 300 chars, spoken)",
            "call_to_action": "str (max 200 chars)",
            "thumbnail_concept": "str (max 400 chars)",
        },
    },
}

ANGLES = [
    "Problem-first",
    "Benefit-first",
    "Story / social proof",
    "Question-led",
    "Offer / urgency-led",
]


def build_content_prompt(
    platform: ContentPlatform,
    campaign: dict,
    strategy: dict,
    count: int,
    avoid: list[str] | None = None,
    start_angle: int = 0,
    repair_note: str | None = None,
) -> str:
    spec = _PLATFORM_BRIEFS[platform]
    angles = [ANGLES[(start_angle + i) % len(ANGLES)] for i in range(count)]
    brief = {
        "product_name": campaign["product_name"],
        "product_description": campaign.get("product_description", ""),
        "campaign_objective": campaign["objective"],
        "tone": campaign["tone"],
        "output_language": campaign.get("language", "English"),
    }
    # Only hand the model the strategy fields that matter for copywriting.
    s = strategy
    strategy_view = {
        "campaign_idea": s.get("campaign_idea"),
        "target_audience": {
            "summary": s.get("target_audience", {}).get("summary"),
            "pain_points": s.get("target_audience", {}).get("pain_points"),
        },
        "key_selling_points": s.get("key_selling_points"),
        "content_tone": s.get("content_tone"),
        "call_to_action": s.get("call_to_action"),
    }
    parts = [
        f"TASK: write {count} different {spec['name']} variation(s).",
        spec["brief"],
        "CAMPAIGN BRIEF:\n" + json.dumps(brief, ensure_ascii=False, indent=2),
        "APPROVED MARKETING STRATEGY:\n" + json.dumps(strategy_view, ensure_ascii=False, indent=2),
        "Use these angles, one per variation, in this order: " + ", ".join(angles) + ".",
    ]
    if avoid:
        parts.append(
            "These texts already exist - write something clearly different from all of them:\n- "
            + "\n- ".join(a[:140] for a in avoid)
        )
    if repair_note:
        parts.append(f"YOUR PREVIOUS REPLY WAS REJECTED: {repair_note}\nFix this and return ONLY the JSON object.")
    parts.append(
        f"Return JSON in exactly this shape, with the 'variations' array holding exactly {count} item(s):\n"
        + json.dumps({"variations": [spec["shape"]]}, indent=2, ensure_ascii=False)
    )
    return "\n\n".join(parts)
