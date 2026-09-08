from __future__ import annotations

import base64
import json
import re
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    api_key: str = ""

    supabase_url: str = ""
    supabase_service_role_key: str = Field(default="", repr=False)
    supabase_expected_host: str = ""
    supabase_timeout_seconds: float = Field(default=10.0, ge=0.1, le=30)
    readiness_timeout_seconds: float = Field(default=3.0, ge=0.1, le=10)
    maintenance_mode: bool = False
    environment: str = "production"
    supabase_allow_local: bool = False
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

    def validate_supabase(self) -> None:
        """Validate configuration only; JWT claims here are not authentication."""
        try:
            raw = self.supabase_url
            parsed = urlsplit(raw)
            host = parsed.hostname or ""
            local = host in {"localhost", "127.0.0.1", "::1"}
            allowed_local = local and self.supabase_allow_local and self.environment == "development"
            if (
                not raw or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in raw)
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or "?" in raw or "#" in raw
                or parsed.path not in {"", "/"}
                or not host or host != self.supabase_expected_host
                or (local and not allowed_local)
                or (parsed.scheme != "https" and not (allowed_local and parsed.scheme == "http"))
                or (not allowed_local and parsed.port not in {None, 443})
                or (not local and not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host))
            ):
                raise ValueError()
        except (ValueError, TypeError):
            raise RuntimeError("Invalid Supabase URL or expected host configuration") from None
        key = self.supabase_service_role_key
        if not key or any(c.isspace() for c in key):
            raise RuntimeError("Supabase service key is required and must not contain whitespace")
        if re.fullmatch(r"sb_secret_[A-Za-z0-9_-]+", key):
            return
        try:
            header, payload, signature = key.split(".")
            if not header or not signature:
                raise ValueError()
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            expected_ref = "local" if allowed_local else host.split(".")[0]
            if claims.get("role") != "service_role" or claims.get("ref") != expected_ref:
                raise ValueError()
        except Exception:
            raise RuntimeError("Invalid Supabase service key role or project reference") from None

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
