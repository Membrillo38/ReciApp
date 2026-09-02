from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.db import get_supabase
from app.models import Ingredient, Platform, Recipe, Step


def recipe_from_row(row: dict) -> Recipe:
    return Recipe(
        id=UUID(row["id"]) if row.get("id") else None,
        title=row["title"],
        ingredients=[Ingredient(**i) for i in (row.get("ingredients") or [])],
        steps=[Step(**s) for s in (row.get("steps") or [])],
        servings=row.get("servings"),
        prep_minutes=row.get("prep_minutes"),
        cook_minutes=row.get("cook_minutes"),
        tags=row.get("tags") or [],
        confidence=float(row.get("confidence") or 0.5),
        missing_fields=row.get("missing_fields") or [],
        source_url=row.get("source_url_raw") or row.get("source_url") or "",
        platform=Platform(row.get("platform") or "unknown"),
        thumbnail_url=row.get("thumbnail_url"),
        author=row.get("author"),
        description=row.get("description"),
        raw_transcript=row.get("raw_transcript"),
    )


def recipe_to_row(recipe: Recipe, *, source_url_norm: str) -> dict:
    return {
        "source_url_raw": recipe.source_url,
        "source_url_norm": source_url_norm,
        "platform": recipe.platform.value,
        "title": recipe.title,
        "description": recipe.description,
        "author": recipe.author,
        "thumbnail_url": recipe.thumbnail_url,
        "ingredients": [i.model_dump() for i in recipe.ingredients],
        "steps": [s.model_dump() for s in recipe.steps],
        "servings": recipe.servings,
        "prep_minutes": recipe.prep_minutes,
        "cook_minutes": recipe.cook_minutes,
        "tags": recipe.tags,
        "confidence": recipe.confidence,
        "missing_fields": recipe.missing_fields,
        "raw_transcript": recipe.raw_transcript,
    }


def get_recipe_by_norm(url_norm: str) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("recipes")
        .select("*")
        .eq("source_url_norm", url_norm)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def upsert_recipe(recipe: Recipe, *, source_url_norm: str) -> dict:
    sb = get_supabase()
    existing = get_recipe_by_norm(source_url_norm)
    payload = recipe_to_row(recipe, source_url_norm=source_url_norm)
    if existing:
        res = sb.table("recipes").update(payload).eq("id", existing["id"]).execute()
        return (res.data or [existing])[0]
    res = sb.table("recipes").insert(payload).execute()
    return res.data[0]


def save_user_recipe(user_id: UUID, recipe_id: UUID) -> None:
    sb = get_supabase()
    sb.table("user_recipes").upsert(
        {"user_id": str(user_id), "recipe_id": str(recipe_id)}
    ).execute()


def list_user_recipes(user_id: UUID) -> list[dict]:
    sb = get_supabase()
    links = (
        sb.table("user_recipes")
        .select("saved_at,recipe_id,recipes(*)")
        .eq("user_id", str(user_id))
        .order("saved_at", desc=True)
        .execute()
    )
    out = []
    for row in links.data or []:
        recipe = row.get("recipes")
        if recipe:
            recipe = dict(recipe)
            recipe["saved_at"] = row.get("saved_at")
            out.append(recipe)
    return out


def delete_user_recipe(user_id: UUID, recipe_id: UUID) -> bool:
    sb = get_supabase()
    res = (
        sb.table("user_recipes")
        .delete()
        .eq("user_id", str(user_id))
        .eq("recipe_id", str(recipe_id))
        .execute()
    )
    return bool(res.data)


def create_job(
    *,
    user_id: UUID,
    source_url_raw: str,
    source_url_norm: str,
    status: str = "pending",
    cache_hit: bool = False,
    recipe_id: UUID | None = None,
    cost_cents: float = 0,
) -> dict:
    sb = get_supabase()
    payload = {
        "user_id": str(user_id),
        "status": status,
        "source_url_raw": source_url_raw,
        "source_url_norm": source_url_norm,
        "cache_hit": cache_hit,
        "cost_cents": cost_cents,
        "recipe_id": str(recipe_id) if recipe_id else None,
    }
    res = sb.table("extract_jobs").insert(payload).execute()
    return res.data[0]


def update_job(job_id: UUID, **fields) -> dict | None:
    sb = get_supabase()
    clean = {k: (str(v) if isinstance(v, UUID) else v) for k, v in fields.items()}
    res = sb.table("extract_jobs").update(clean).eq("id", str(job_id)).execute()
    return (res.data or [None])[0]


def get_job(job_id: UUID) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("extract_jobs")
        .select("*")
        .eq("id", str(job_id))
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def list_jobs(limit: int = 50) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("extract_jobs")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def list_recipes(limit: int = 50) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("recipes")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def get_recipe(recipe_id: UUID) -> dict | None:
    sb = get_supabase()
    res = (
        sb.table("recipes")
        .select("*")
        .eq("id", str(recipe_id))
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def list_profiles(limit: int = 100) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("profiles")
        .select("*")
        .is_("deleted_at", "null")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def soft_delete_profile(user_id: UUID) -> None:
    sb = get_supabase()
    sb.table("profiles").update(
        {"deleted_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", str(user_id)).execute()


def week_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=start.weekday())
