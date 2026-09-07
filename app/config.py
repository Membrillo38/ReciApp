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
    dashboard_totp_secret: str = ""
    dashboard_cookie_secure: bool = True

    cors_origins: str = "https://reciapp-4ih5.onrender.com"
    billing_guard_enabled: bool = True
    daily_api_budget_cents: float = 1000.0
    monthly_api_budget_cents: float = 5000.0
    user_monthly_budget_cents: float = 500.0
    max_job_cost_cents: float = 100.0
    max_concurrent_jobs: int = 8
    max_concurrent_jobs_per_user: int = 2
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
    rate_limit_per_ip_per_minute: int = 60
    rate_limit_per_user_per_minute: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
