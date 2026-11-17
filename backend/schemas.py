import re
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Platform(str, Enum):
    instagram = "Instagram"
    facebook = "Facebook"
    linkedin = "LinkedIn"
    x = "X (Twitter)"
    tiktok = "TikTok"
    youtube = "YouTube"
    email = "Email"
    google_ads = "Google Ads"
    blog = "Website / Blog"


class Objective(str, Enum):
    awareness = "Brand Awareness"
    leads = "Lead Generation"
    sales = "Sales / Conversions"
    engagement = "Engagement"
    launch = "Product Launch"
    retention = "Customer Retention"


class Tone(str, Enum):
    professional = "Professional"
    friendly = "Friendly"
    playful = "Playful"
    luxury = "Luxury"
    bold = "Bold"
    inspirational = "Inspirational"
    informative = "Informative"
    urgent = "Urgent"


LANGUAGES = [
    "English", "Urdu", "Hindi", "Arabic", "Spanish", "French",
    "German", "Portuguese", "Turkish", "Chinese", "Japanese", "Indonesian",
]


class CampaignInput(BaseModel):
    product_name: str = Field(..., min_length=2, max_length=100)
    product_description: str = Field(..., min_length=20, max_length=2000)
    target_audience: str = Field(..., min_length=5, max_length=500)
    platform: Platform
    objective: Objective
    tone: Tone
    language: str = "English"

    @field_validator("product_name", "product_description", "target_audience", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

    @field_validator("product_name", "product_description", "target_audience")
    @classmethod
    def _must_have_letters(cls, v: str) -> str:
        if not re.search(r"[^\W\d_]", v):
            raise ValueError("Please enter meaningful text, not only numbers or symbols.")
        return v

    @field_validator("language")
    @classmethod
    def _language_ok(cls, v: str) -> str:
        if v not in LANGUAGES:
            raise ValueError(f"Unsupported language. Choose one of: {', '.join(LANGUAGES)}")
        return v


# ---------- Structured strategy returned by the LLM ----------
class CampaignIdea(BaseModel):
    title: str
    concept: str
    hook: str


class AudienceProfile(BaseModel):
    summary: str
    demographics: list[str]
    psychographics: list[str]
    pain_points: list[str]


class SellingPoint(BaseModel):
    point: str
    benefit: str


class ContentTone(BaseModel):
    voice: str
    style_guidelines: list[str]
    words_to_use: list[str]
    words_to_avoid: list[str]


class CallToAction(BaseModel):
    primary: str
    alternatives: list[str]


class ContentType(BaseModel):
    type: str
    description: str
    why_it_works: str


class MarketingStrategy(BaseModel):
    campaign_idea: CampaignIdea
    target_audience: AudienceProfile
    key_selling_points: list[SellingPoint] = Field(..., min_length=3)
    content_tone: ContentTone
    call_to_action: CallToAction
    suggested_content_types: list[ContentType] = Field(..., min_length=3)
    success_metrics: list[str]
