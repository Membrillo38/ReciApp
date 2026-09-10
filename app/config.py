from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    api_key: str = ""

    database_url: str = Field(default="", repr=False)
    redis_url: str = Field(default="", repr=False)
    auth_jwt_secret: str = Field(default="", repr=False)
    auth_jwt_issuer: str = "reciapp-api"
    auth_jwt_audience: str = "reciapp-ios"
    auth_access_token_ttl_seconds: int = 3600
    auth_refresh_token_ttl_seconds: int = 60 * 60 * 24 * 60
    cover_public_base_url: str = ""
    readiness_timeout_seconds: float = Field(default=3.0, ge=0.1, le=10)
    maintenance_mode: bool = False
    environment: str = "production"

    max_duration_seconds: int = 600
    transcribe_model: str = "gpt-4o-mini-transcribe"
    recipe_model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"
    job_ttl_seconds: int = 3600

    cost_transcribe_cents_per_min: float = 0.3
    cost_text_cents_per_extract: float = 0.1
    cost_ocr_cents_per_slide: float = 0.25
    # List prices used for real dashboard cost (USD per 1M tokens / per minute).
    openai_chat_input_usd_per_mtok: float = 0.15
    openai_chat_output_usd_per_mtok: float = 0.60
    openai_chat_cached_input_usd_per_mtok: float = 0.075
    openai_transcribe_input_usd_per_mtok: float = 1.25
    openai_transcribe_output_usd_per_mtok: float = 5.0
    openai_transcribe_usd_per_min: float = 0.003
    local_whisper_model: str = "tiny"
    local_whisper_timeout_seconds: float = 120.0

    superwall_webhook_secret: str = ""
    superwall_application_id: int = 54783
    public_api_base_url: str = "https://reciapp-4ih5.onrender.com"

    dashboard_password: str = ""
    dashboard_session_secret: str = ""
    dashboard_totp_secret: str = ""
    dashboard_cookie_secure: bool = True

    cors_origins: str = "https://reciapp-4ih5.onrender.com"
    billing_guard_enabled: bool = True
    daily_api_budget_cents: float = 1000.0
    monthly_api_budget_cents: float = 5000.0
    user_monthly_budget_cents: float = 500.0
    max_job_cost_cents: float = 100.0
    max_concurrent_jobs: int = 8
    # Process slots (extract + translation). Serial extract starts are gated in
    # extract_recipe via user_has_processing_extract, not this counter alone.
    max_concurrent_jobs_per_user: int = 2
    max_pending_jobs_per_user: int = 20
    # Web requests use FastAPI BackgroundTasks by default. A separate worker
    # can be enabled after the durable lease migration is deployed.
    worker_enabled: bool = False
    worker_poll_seconds: float = 5.0
    worker_lease_seconds: int = 900
    max_request_body_bytes: int = 262_144
    webhook_max_age_seconds: int = 7 * 24 * 60 * 60
    apple_root_ca_pem: str = ""
    apple_bundle_id: str = "com.membri.reciapp"
    apple_environment: str = "Production"
    trusted_proxy_ips: str = ""
    rate_limit_per_ip_per_minute: int = 180
    rate_limit_per_user_per_minute: int = 120
    rate_limit_extract_per_ip_per_minute: int = 15
    rate_limit_extract_per_user_per_minute: int = 10
    rate_limit_extract_daily_per_user: int = 100

    def validate_database(self) -> None:
        """Validate DATABASE_URL shape without logging credentials."""
        try:
            raw = self.database_url
            parsed = urlsplit(raw)
            if not raw or parsed.scheme != "postgresql" or not parsed.hostname:
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError("DATABASE_URL is required and must start with postgresql://") from None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
