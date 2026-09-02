from __future__ import annotations

from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class Platform(str, Enum):
    tiktok = "tiktok"
    youtube = "youtube"
    instagram = "instagram"
    facebook = "facebook"
    unknown = "unknown"


class Ingredient(BaseModel):
    name: str
    quantity: str | None = None
    unit: str | None = None


class Step(BaseModel):
    order: int
    text: str
    duration_minutes: int | None = None


class Recipe(BaseModel):
    title: str
    ingredients: list[Ingredient]
    steps: list[Step]
    servings: int | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    tags: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1, default=0.5)
    missing_fields: list[str] = Field(default_factory=list)
    source_url: str
    platform: Platform
    thumbnail_url: str | None = None
    author: str | None = None
    description: str | None = None
    raw_transcript: str | None = None


class ExtractRequest(BaseModel):
    url: HttpUrl


class JobStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ExtractJobResponse(BaseModel):
    job_id: UUID
    status: JobStatus


class JobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    recipe: Recipe | None = None
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
