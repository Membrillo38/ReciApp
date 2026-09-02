from __future__ import annotations

from enum import Enum
from typing import Any, Literal
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
    id: UUID | None = None
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
    cache_hit: bool = False


class JobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    cache_hit: bool = False
    cost_cents: float = 0
    recipe: Recipe | None = None
    error: str | None = None


class MeResponse(BaseModel):
    id: UUID
    email: str | None
    display_name: str | None
    is_pro: bool
    pro_expires_at: str | None
    free_used_this_week: int
    free_limit: int
    free_remaining: int
    pro_cost_cents_this_month: float
    pro_budget_cents: float
    pro_remaining_cents: float


class AdminUserCreate(BaseModel):
    email: str
    display_name: str | None = None
    is_pro: bool = False
    password: str | None = None


class AdminUserPatch(BaseModel):
    display_name: str | None = None
    is_pro: bool | None = None
    pro_expires_at: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class OkResponse(BaseModel):
    ok: bool = True


class ListResponse(BaseModel):
    items: list[dict[str, Any]]
