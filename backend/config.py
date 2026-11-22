from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "ai_marketing"
    use_mock_db: bool = False

    llm_provider: str = "mock"  # anthropic | openai | gemini | mock
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Accepts GEMINI_API_KEY or GOOGLE_API_KEY in .env
    gemini_api_key: str = Field(default="", validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY"))
    gemini_model: str = "gemini-2.5-flash"
    gemini_fallback_models: str = "gemini-2.5-pro"

    cors_origins: str = "http://localhost:5173"

    # ---------- Phase 3: image generation ----------
    image_provider: str = "mock"  # gemini | openai | mock
    gemini_image_model: str = "gemini-2.5-flash-image"
    gemini_image_fallback_models: str = ""  # comma separated, tried when the first model fails
    openai_image_model: str = "gpt-image-1"
    openai_image_quality: str = "medium"  # low | medium | high
    storage_dir: str = "storage"  # generated creatives + uploaded product images live here
    max_upload_mb: int = 5

    # ---------- Phase 5: production, security, monitoring, cost control ----------
    environment: str = "development"  # development | production  (production adds HSTS, hides docs)
    log_level: str = "INFO"
    log_json: bool = False  # true = one JSON object per line (best for Render / Railway / CloudWatch log search)
    log_file: str = ""  # optional rotating log file, e.g. logs/app.log
    rate_limit_per_minute: int = 30  # AI endpoints, per client IP. 0 = off. Skipped when both providers are 'mock'.
    max_body_mb: int = 12  # reject larger request bodies early (product image upload is <= max_upload_mb)
    strategy_cache_hours: int = 72  # an identical brief inside this window reuses the saved strategy (0 = off)
    admin_token: str = ""  # protects GET /api/metrics via the X-Admin-Token header; empty = metrics only in development
    frontend_dist: str = ""  # path of the built frontend; empty = auto-detect ../frontend/dist

    @field_validator("gemini_api_key", "anthropic_api_key", "openai_api_key", "admin_token", mode="before")
    @classmethod
    def _clean_key(cls, v):
        # remove accidental spaces / quotes copied into .env
        return v.strip().strip('"').strip("'").strip() if isinstance(v, str) else v

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()