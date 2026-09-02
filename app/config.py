from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    api_key: str = ""
    max_duration_seconds: int = 600
    transcribe_model: str = "gpt-4o-mini-transcribe"
    recipe_model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"
    job_ttl_seconds: int = 3600


settings = Settings()
