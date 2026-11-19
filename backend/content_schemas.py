"""Phase 2 - structured output schemas for platform-specific content.

Every platform has its own Pydantic model, so the UI never has to parse free text:
it renders named fields (hook, headline, thumbnail_concept ...). The same models
validate what the LLM returns, so incomplete / malformed data is rejected early.
"""

import re
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, field_validator
from pydantic.functional_validators import BeforeValidator


class ContentPlatform(str, Enum):
    instagram = "instagram"
    instagram_story = "instagram_story"
    linkedin = "linkedin"
    facebook = "facebook"
    youtube = "youtube"


def _clean_text(v):
    """Strip whitespace; treat non-strings (None, numbers) as invalid early."""
    if isinstance(v, str):
        return re.sub(r"[ \t]+\n", "\n", v).strip()
    return v


Text = Annotated[str, BeforeValidator(_clean_text)]


def _normalise_hashtags(v):
    """Accept list or 'a b #c' string; return unique '#tag' items, max 30."""
    if isinstance(v, str):
        v = re.split(r"[,\s]+", v)
    if not isinstance(v, list):
        return v
    out: list[str] = []
    for item in v:
        if not isinstance(item, str):
            continue
        tag = re.sub(r"[^\w]", "", item.strip().lstrip("#"), flags=re.UNICODE)
        if tag and f"#{tag}".lower() not in {t.lower() for t in out}:
            out.append(f"#{tag}")
    return out[:30]


Hashtags = Annotated[list[str], BeforeValidator(_normalise_hashtags)]


class _Piece(BaseModel):
    """Base: every non-empty-string field must really contain text."""

    @field_validator("*", mode="after")
    @classmethod
    def _not_blank(cls, v, info):
        required = cls.model_fields[info.field_name].is_required()
        if required and isinstance(v, str) and not v.strip():
            raise ValueError(f"'{info.field_name}' must not be empty")
        return v


class InstagramCaption(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)  # e.g. "Problem-first"
    hook: Text = Field(..., min_length=3, max_length=150)
    main_message: Text = Field(..., min_length=10, max_length=1500)
    call_to_action: Text = Field(..., min_length=2, max_length=150)
    hashtags: Hashtags = Field(..., min_length=3, max_length=30)


class StoryFrame(_Piece):
    visual: Text = Field(..., min_length=3, max_length=300)
    text_overlay: Text = Field(..., min_length=2, max_length=120)
    interaction: Text = Field(default="", max_length=120)  # poll / quiz / link sticker (optional)


class InstagramStory(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)
    hook: Text = Field(..., min_length=3, max_length=150)
    frames: list[StoryFrame] = Field(..., min_length=3, max_length=6)
    call_to_action: Text = Field(..., min_length=2, max_length=150)


class LinkedInPost(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)
    introduction: Text = Field(..., min_length=10, max_length=400)
    value_proposition: Text = Field(..., min_length=10, max_length=500)
    main_content: Text = Field(..., min_length=30, max_length=2000)
    call_to_action: Text = Field(..., min_length=2, max_length=200)
    hashtags: Hashtags = Field(..., min_length=2, max_length=10)


class FacebookAd(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)
    headline: Text = Field(..., min_length=3, max_length=80)
    primary_text: Text = Field(..., min_length=15, max_length=700)
    call_to_action: Text = Field(..., min_length=2, max_length=60)
    short_description: Text = Field(default="", max_length=120)  # optional


class YouTubeContent(_Piece):
    angle: Text = Field(..., min_length=2, max_length=60)
    video_title: Text = Field(..., min_length=5, max_length=100)  # YouTube hard limit
    description: Text = Field(..., min_length=30, max_length=2500)
    hook: Text = Field(..., min_length=5, max_length=300)
    call_to_action: Text = Field(..., min_length=2, max_length=200)
    thumbnail_concept: Text = Field(..., min_length=10, max_length=400)


# platform -> (model, label, human readable ordered fields used by the UI + copy)
PLATFORM_MODELS: dict[ContentPlatform, type[BaseModel]] = {
    ContentPlatform.instagram: InstagramCaption,
    ContentPlatform.instagram_story: InstagramStory,
    ContentPlatform.linkedin: LinkedInPost,
    ContentPlatform.facebook: FacebookAd,
    ContentPlatform.youtube: YouTubeContent,
}

PLATFORM_META = {
    ContentPlatform.instagram: {
        "label": "Instagram Captions",
        "fields": ["hook", "main_message", "call_to_action", "hashtags"],
    },
    ContentPlatform.instagram_story: {
        "label": "Instagram Stories",
        "fields": ["hook", "frames", "call_to_action"],
    },
    ContentPlatform.linkedin: {
        "label": "LinkedIn Posts",
        "fields": ["introduction", "value_proposition", "main_content", "call_to_action", "hashtags"],
    },
    ContentPlatform.facebook: {
        "label": "Facebook Ads",
        "fields": ["headline", "primary_text", "call_to_action", "short_description"],
    },
    ContentPlatform.youtube: {
        "label": "YouTube Content",
        "fields": ["video_title", "hook", "description", "call_to_action", "thumbnail_concept"],
    },
}


# ---------- API request bodies ----------
class GenerateContentRequest(BaseModel):
    platforms: list[ContentPlatform] = Field(default_factory=lambda: list(ContentPlatform), min_length=1)
    variations: int = Field(default=3, ge=1, le=5)


class RegenerateRequest(BaseModel):
    variations: int = Field(default=3, ge=1, le=5)
    index: int | None = Field(default=None, ge=0, le=9)  # None -> regenerate all, n -> only variation n


class SelectRequest(BaseModel):
    index: int = Field(..., ge=0, le=9)
