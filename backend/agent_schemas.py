"""Phase 4 - asset catalog, planner/agent request bodies and the schemas of the two new asset types
(reel concept, promotional caption). Phase 2 platform copy and Phase 3 creatives are reused as they are."""
from typing import Literal
from enum import Enum

from pydantic import BaseModel, Field, field_validator

import agent_guard
from content_schemas import Hashtags, Text, _Piece
from schemas import CampaignInput

# ---------- asset catalog: everything the planner can choose from ----------
# kind "content" -> Phase 2 copy (+ optional Phase 3 visual); "reel"/"promo" -> new Phase 4 text assets.
ASSETS: dict[str, dict] = {
    "instagram_post": {
        "label": "Instagram post", "kind": "content", "platform": "Instagram",
        "content_platform": "instagram", "creative_format": "instagram_post",
        "description": "Feed caption with hook, message, CTA and hashtags, plus a square image.",
    },
    "instagram_story": {
        "label": "Instagram story", "kind": "content", "platform": "Instagram",
        "content_platform": "instagram_story", "creative_format": "instagram_story",
        "description": "3-5 frame story sequence plus a full-screen vertical visual.",
    },
    "instagram_reel": {
        "label": "Reel / short-video concept", "kind": "reel", "platform": "Instagram / TikTok",
        "content_platform": None, "creative_format": None,
        "description": "Scene-by-scene short video idea with hook, audio direction and a cover image prompt.",
    },
    "promo_caption": {
        "label": "Promotional caption", "kind": "promo", "platform": "Any",
        "content_platform": None, "creative_format": None,
        "description": "Short offer-led caption with headline, call to action and hashtags.",
    },
    "linkedin_post": {
        "label": "LinkedIn post", "kind": "content", "platform": "LinkedIn",
        "content_platform": "linkedin", "creative_format": "linkedin_creative",
        "description": "Professional post with value proposition plus a wide creative.",
    },
    "facebook_ad": {
        "label": "Facebook ad", "kind": "content", "platform": "Facebook",
        "content_platform": "facebook", "creative_format": "facebook_ad",
        "description": "Headline, primary text and button label plus a portrait feed image.",
    },
    "youtube_video": {
        "label": "YouTube video", "kind": "content", "platform": "YouTube",
        "content_platform": "youtube", "creative_format": "youtube_thumbnail",
        "description": "Title, hook, description and CTA plus a thumbnail.",
    },
}
ASSET_KEYS = list(ASSETS)

# What the rule-based planner (also the fallback when the AI planner fails) creates per campaign platform.
PLATFORM_DEFAULTS: dict[str, list[str]] = {
    "Instagram": ["instagram_post", "instagram_story", "instagram_reel", "promo_caption"],
    "Facebook": ["facebook_ad", "promo_caption"],
    "LinkedIn": ["linkedin_post", "promo_caption"],
    "YouTube": ["youtube_video", "promo_caption"],
    "TikTok": ["instagram_reel", "instagram_story", "promo_caption"],
    "X (Twitter)": ["promo_caption", "instagram_post"],
    "Email": ["promo_caption", "linkedin_post"],
    "Google Ads": ["facebook_ad", "promo_caption"],
    "Website / Blog": ["linkedin_post", "promo_caption"],
}


def asset_meta(key: str) -> dict:
    a = ASSETS[key]
    return {"key": key, "label": a["label"], "kind": a["kind"], "platform": a["platform"],
            "description": a["description"], "has_image": bool(a["creative_format"])}


def _check_keys(v):
    if v is None:
        return v
    bad = [k for k in v if k not in ASSETS]
    if bad:
        raise ValueError(f"Unknown asset type: {', '.join(bad)}")
    v = list(dict.fromkeys(v))
    if not v:
        raise ValueError("Choose at least one asset.")
    if len(v) > agent_guard.MAX_ASSETS_PER_RUN:
        raise ValueError(f"At most {agent_guard.MAX_ASSETS_PER_RUN} assets per run.")
    return v


# ---------- API request bodies ----------
class AgentRunRequest(CampaignInput):
    """The campaign brief (same validated fields as Phase 1) plus agent options."""
    variations: int = Field(default=2, ge=1, le=agent_guard.MAX_VARIATIONS)
    concepts: int = Field(default=2, ge=1, le=agent_guard.MAX_CONCEPTS)
    generate_images: bool = True
    require_plan_approval: bool = False
    assets: list[str] | None = None  # optional manual override of the AI planner

    @field_validator("assets")
    @classmethod
    def _assets_ok(cls, v):
        return _check_keys(v)


class ContinueRequest(BaseModel):
    assets: list[str] | None = None

    @field_validator("assets")
    @classmethod
    def _assets_ok(cls, v):
        return _check_keys(v)


class Scope(str, Enum):
    strategy = "strategy"
    plan = "plan"          # build the asset plan for a campaign created before Phase 4
    caption = "caption"
    image = "image"
    campaign = "campaign"


class AgentRegenerateRequest(BaseModel):
    scope: Scope
    target: str | None = None  # asset key, required for caption / image
    cascade: bool = False      # scope=strategy: also rewrite copy and visuals from the new strategy
    variations: int = Field(default=2, ge=1, le=agent_guard.MAX_VARIATIONS)
    concepts: int = Field(default=2, ge=1, le=agent_guard.MAX_CONCEPTS)


class ApprovalRequest(BaseModel):
    approvals: dict[str, Literal["approved", "pending", "rejected"]] = Field(..., min_length=1)


class ExportRequest(BaseModel):
    confirm: bool = False
    assets: list[str] | None = None
    format: Literal["markdown", "json"] = "markdown"


# ---------- new asset schemas (validated exactly like Phase 2 copy) ----------
class ReelScene(_Piece):
    visual: Text = Field(..., min_length=3, max_length=300)
    on_screen_text: Text = Field(..., min_length=2, max_length=120)
    seconds: int = Field(..., ge=1, le=30)


class ReelConcept(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)
    title: Text = Field(..., min_length=3, max_length=100)
    hook: Text = Field(..., min_length=3, max_length=200)
    scenes: list[ReelScene] = Field(..., min_length=3, max_length=6)
    audio_suggestion: Text = Field(..., min_length=3, max_length=200)
    call_to_action: Text = Field(..., min_length=2, max_length=150)
    caption: Text = Field(..., min_length=10, max_length=800)
    hashtags: Hashtags = Field(..., min_length=3, max_length=15)
    cover_image_prompt: Text = Field(..., min_length=30, max_length=600)


class PromoCaption(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)
    headline: Text = Field(..., min_length=3, max_length=80)
    caption: Text = Field(..., min_length=15, max_length=600)
    offer_line: Text = Field(default="", max_length=120)
    call_to_action: Text = Field(..., min_length=2, max_length=100)
    hashtags: Hashtags = Field(..., min_length=2, max_length=12)


EXTRA_MODELS = {"instagram_reel": ReelConcept, "promo_caption": PromoCaption}
EXTRA_FIELDS = {
    "instagram_reel": ["title", "hook", "scenes", "audio_suggestion", "call_to_action", "caption", "hashtags", "cover_image_prompt"],
    "promo_caption": ["headline", "caption", "offer_line", "call_to_action", "hashtags"],
}
