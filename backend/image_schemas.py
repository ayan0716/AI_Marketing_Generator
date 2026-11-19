"""Phase 3 - creative formats, structured image-concept schema and API request bodies."""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from content_schemas import Text, _Piece

class CreativeFormat(str, Enum):
    instagram_post = "instagram_post"
    instagram_story = "instagram_story"
    linkedin_creative = "linkedin_creative"
    facebook_ad = "facebook_ad"
    youtube_thumbnail = "youtube_thumbnail"

# One spec per creative format. These drive BOTH the image prompt (composition rules, audience)
# and the API call (aspect ratio / size), so every platform gets a correctly shaped visual.
FORMAT_SPECS: dict[CreativeFormat, dict] = {
    CreativeFormat.instagram_post: {
        "label": "Instagram Post", "platform": "Instagram", "content_platform": "instagram",
        "aspect": "1:1", "openai_size": "1024x1024", "width": 1080, "height": 1080,
        "audience": "mobile users scrolling a fast, visual feed who decide in under a second",
        "composition": (
            "Square 1:1 composition. One clear focal subject placed on the rule of thirds, generous negative "
            "space, high contrast so it still reads as a small thumbnail in the grid."
        ),
        "summary": "Square feed image, 1080 x 1080",
    },
    CreativeFormat.instagram_story: {
        "label": "Instagram Story", "platform": "Instagram", "content_platform": "instagram_story",
        "aspect": "9:16", "openai_size": "1024x1536", "width": 1080, "height": 1920,
        "audience": "mobile users tapping quickly through full-screen vertical stories",
        "composition": (
            "Tall vertical 9:16 full-screen composition. Keep the top 14% and bottom 20% free of important "
            "details (Story interface safe zones). Place the subject in the middle band, leave calm space "
            "for text stickers."
        ),
        "summary": "Full-screen vertical, 1080 x 1920",
    },
    CreativeFormat.linkedin_creative: {
        "label": "LinkedIn Creative", "platform": "LinkedIn", "content_platform": "linkedin",
        "aspect": "16:9", "openai_size": "1536x1024", "width": 1200, "height": 627,
        "audience": "professionals and decision makers who respond to credibility, clarity and polish",
        "composition": (
            "Wide landscape composition (about 1.91:1). Clean, uncluttered, professional layout with the "
            "subject on one side and breathing room on the other. Restrained palette, no gimmicks."
        ),
        "summary": "Wide landscape, 1200 x 627",
    },
    CreativeFormat.facebook_ad: {
        "label": "Facebook Ad", "platform": "Facebook", "content_platform": "facebook",
        "aspect": "4:5", "openai_size": "1024x1536", "width": 1080, "height": 1350,
        "audience": "a broad audience in the mobile news feed, driven by a clear benefit and a call to action",
        "composition": (
            "Portrait 4:5 composition that fills the mobile feed. Product or key benefit large and obvious, "
            "bright and friendly, with a clear empty area near the bottom for a headline and button."
        ),
        "summary": "Portrait feed ad, 1080 x 1350",
    },
    CreativeFormat.youtube_thumbnail: {
        "label": "YouTube Thumbnail", "platform": "YouTube", "content_platform": "youtube",
        "aspect": "16:9", "openai_size": "1536x1024", "width": 1280, "height": 720,
        "audience": "viewers browsing search results and the home feed, deciding what to click",
        "composition": (
            "Landscape 16:9 thumbnail. Very bold, saturated and high contrast, one large subject (a product or "
            "an expressive face) on one side, simple background, big empty area on the opposite side for a "
            "3-5 word title. Must be readable at very small sizes."
        ),
        "summary": "Landscape thumbnail, 1280 x 720",
    },
}
for _s in FORMAT_SPECS.values():
    _s["ratio"] = _s["width"] / _s["height"]

def format_meta(fmt: CreativeFormat) -> dict:
    s = FORMAT_SPECS[fmt]
    return {"key": fmt.value, "label": s["label"], "platform": s["platform"], "aspect": s["aspect"],
            "width": s["width"], "height": s["height"], "summary": s["summary"]}

# ---------- structured concept returned by the prompt-writing LLM ----------
class ImageConcept(_Piece):
    name: Text = Field(..., min_length=3, max_length=70)
    style_label: Text = Field(..., min_length=3, max_length=50)
    concept_summary: Text = Field(..., min_length=10, max_length=320)
    visual_style: Text = Field(..., min_length=3, max_length=200)
    composition: Text = Field(..., min_length=5, max_length=300)
    background: Text = Field(..., min_length=3, max_length=250)
    lighting: Text = Field(..., min_length=3, max_length=200)
    color_palette: list[Text] = Field(..., min_length=2, max_length=6)
    product_placement: Text = Field(..., min_length=5, max_length=300)
    mood: Text = Field(..., min_length=3, max_length=120)
    text_overlay: Text = Field(default="", max_length=80)  # optional caption idea, added outside the image
    image_prompt: Text = Field(..., min_length=60, max_length=1800)
    negative_prompt: Text = Field(default="", max_length=300)

    @field_validator("color_palette", mode="before")
    @classmethod
    def _palette(cls, v):
        if isinstance(v, str):
            v = [x.strip() for x in v.split(",") if x.strip()]
        return v

# ---------- API request bodies ----------
class GenerateCreativesRequest(BaseModel):
    formats: list[CreativeFormat] = Field(default_factory=lambda: list(CreativeFormat), min_length=1)
    concepts: int = Field(default=3, ge=1, le=4)
    use_product_image: bool = True

class ReviseRequest(BaseModel):
    instructions: str = Field(..., min_length=3, max_length=400)
    category: Literal["background", "style", "composition", "tone", "other"] = "other"

    @field_validator("instructions", mode="before")
    @classmethod
    def _strip(cls, v):
        return v.strip() if isinstance(v, str) else v

class SelectCreativeRequest(BaseModel):
    concept_id: str = Field(..., min_length=1, max_length=40)

class VersionRequest(BaseModel):
    version_id: str = Field(..., min_length=1, max_length=40)

class ProductImageUpload(BaseModel):
    data_url: str = Field(..., min_length=30)
