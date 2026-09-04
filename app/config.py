from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    api_key: str = ""

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    max_duration_seconds: int = 600
    transcribe_model: str = "gpt-4o-mini-transcribe"
    recipe_model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"
    job_ttl_seconds: int = 3600

    cost_transcribe_cents_per_min: float = 0.3
    cost_text_cents_per_extract: float = 0.1
    cost_ocr_cents_per_slide: float = 0.25

    superwall_webhook_secret: str = ""
    superwall_application_id: int = 54783
    public_api_base_url: str = "https://reciapp-4ih5.onrender.com"

    dashboard_password: str = ""
    dashboard_session_secret: str = ""
    dashboard_cookie_secure: bool = True


settings = Settings()
