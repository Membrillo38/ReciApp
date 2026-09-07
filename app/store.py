from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

from app.db import get_supabase
from app.localization import ingredient_section_name, normalize_language
from app.translation_cache import get_recipe_translations, source_recipe_fingerprint
from app.models import (
    Ingredient,
    IngredientSection,
    Platform,
    Recipe,
    RecipePublic,
    RecipeSummary,
    RecipeTip,
    Step,
)


class JobAccessUnavailable(RuntimeError):
    """The shared-job access table could not be read or written."""


_MAX_CAROUSEL_IMAGES = 12


def _carousel_urls(values: object) -> list[str]:
    raw_values = values if isinstance(values, list) else []
    urls: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        candidate = str(value or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if len(candidate) > 2048 or candidate in seen:
            continue
        seen.add(candidate)
        urls.append(candidate)
        if len(urls) >= _MAX_CAROUSEL_IMAGES:
            break
    return urls


def _ingredient_sections_from_row(row: dict) -> list[IngredientSection]:
    raw_sections = row.get("ingredient_sections") or []
    if raw_sections:
        return [IngredientSection(**section) for section in raw_sections]

    ingredients = [Ingredient(**ingredient) for ingredient in (row.get("ingredients") or [])]
    language_code = normalize_language(row.get("language_code"))
    return [IngredientSection(title=ingredient_section_name(language_code), ingredients=ingredients)] if ingredients else []


def _flatten_ingredient_sections(sections: list[IngredientSection]) -> list[Ingredient]:
    return [ingredient for section in sections for ingredient in section.ingredients]


def _tips_from_row(row: dict) -> list[RecipeTip]:
    return [RecipeTip(**tip) for tip in (row.get("tips") or [])]


def recipe_from_row(row: dict) -> Recipe:
    ingredient_sections = _ingredient_sections_from_row(row)
    return Recipe(
        id=UUID(row["id"]) if row.get("id") else None,
        title=row["title"],
        ingredients=_flatten_ingredient_sections(ingredient_sections),
        ingredient_sections=ingredient_sections,
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
        carousel_image_urls=_carousel_urls(row.get("carousel_image_urls")),
        author=row.get("author"),
        description=row.get("description"),
        tips=_tips_from_row(row),
        language_code=normalize_language(row.get("language_code")),
        raw_transcript=row.get("raw_transcript"),
    )


def recipe_public_from_row(row: dict) -> RecipePublic:
    rid = row.get("id")
    if not rid:
        raise ValueError("recipe row missing id")
    ingredient_sections = _ingredient_sections_from_row(row)
    return RecipePublic(
        id=UUID(str(rid)),
        title=row["title"],
        ingredients=_flatten_ingredient_sections(ingredient_sections),
        ingredient_sections=ingredient_sections,
        steps=[Step(**s) for s in (row.get("steps") or [])],
        servings=row.get("servings"),
        prep_minutes=row.get("prep_minutes"),
        cook_minutes=row.get("cook_minutes"),
        tags=row.get("tags") or [],
        source_url=row.get("source_url_raw") or row.get("source_url") or "",
        platform=Platform(row.get("platform") or "unknown"),
        thumbnail_url=row.get("thumbnail_url"),
        carousel_image_urls=_carousel_urls(row.get("carousel_image_urls")),
        author=row.get("author"),
        description=row.get("description"),
        tips=_tips_from_row(row),
        language_code=normalize_language(row.get("language_code")),
    )


def recipe_summary_from_row(row: dict, *, saved_at: str) -> RecipeSummary:
    rid = row.get("id")
    if not rid:
        raise ValueError("recipe row missing id")
    return RecipeSummary(
        id=UUID(str(rid)),
        title=row["title"],
        platform=Platform(row.get("platform") or "unknown"),
        source_url=row.get("source_url_raw") or row.get("source_url") or "",
        thumbnail_url=row.get("thumbnail_url"),
        author=row.get("author"),
        servings=row.get("servings"),
        prep_minutes=row.get("prep_minutes"),
        cook_minutes=row.get("cook_minutes"),
        saved_at=saved_at,
        language_code=normalize_language(row.get("language_code")),
    )


def recipe_to_row(recipe: Recipe, *, source_url_norm: str, language_code: str = "en-US") -> dict:
    return {
        "source_url_raw": recipe.source_url,
        "source_url_norm": source_url_norm,
        "language_code": language_code,
        "platform": recipe.platform.value,
        "title": recipe.title,
        "description": recipe.description,
        "author": recipe.author,
        "thumbnail_url": recipe.thumbnail_url,
        "carousel_image_urls": _carousel_urls(recipe.carousel_image_urls),
        "ingredients": [i.model_dump() for i in recipe.ingredients],
        "ingredient_sections": [section.model_dump() for section in recipe.ingredient_sections],
        "steps": [s.model_dump() for s in recipe.steps],
        "servings": recipe.servings,
        "prep_minutes": recipe.prep_minutes,
        "cook_minutes": recipe.cook_minutes,
        "tags": recipe.tags,
        "confidence": recipe.confidence,
        "missing_fields": recipe.missing_fields,
        "raw_transcript": recipe.raw_transcript,
        "tips": [tip.model_dump() for tip in recipe.tips],
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


def upsert_recipe(recipe: Recipe, *, source_url_norm: str, language_code: str = "en-US") -> dict:
    sb = get_supabase()
    existing = get_recipe_by_norm(source_url_norm)
    payload = recipe_to_row(recipe, source_url_norm=source_url_norm, language_code=language_code)

    def write(row_payload: dict) -> dict:
        if existing:
            res = sb.table("recipes").update(row_payload).eq("id", existing["id"]).execute()
            return (res.data or [existing])[0]
        try:
            res = sb.table("recipes").insert(row_payload).execute()
            return res.data[0]
        except Exception as exc:
            # Two workers can pass the read-before-write check together. The
            # database unique constraint is the arbiter; reuse its winning row.
            message = str(exc)
            if "23505" not in message or "source_url_norm" not in message:
                raise
            winner = get_recipe_by_norm(source_url_norm)
            if winner:
                return winner
            raise

    try:
        return write(payload)
    except Exception as exc:
        # Keep extraction compatible during the short rollout window where the
        # server is newer than PostgREST's recipes schema cache. New carousel
        # media is retained automatically once migration 010 is visible.
        message = str(exc).lower()
        if "carousel_image_urls" not in message or "column" not in message:
            raise
        legacy_payload = dict(payload)
        legacy_payload.pop("carousel_image_urls", None)
        return write(legacy_payload)


def save_user_recipe(user_id: UUID, recipe_id: UUID) -> None:
    sb = get_supabase()
    sb.table("user_recipes").upsert(
        {"user_id": str(user_id), "recipe_id": str(recipe_id)}
    ).execute()


_RECIPE_SUMMARY_COLS = (
    "id,title,thumbnail_url,platform,source_url_raw,author,servings,prep_minutes,cook_minutes,language_code"
)


def list_user_recipe_summaries(user_id: UUID, language_code: str = "en-US") -> list[RecipeSummary]:
    sb = get_supabase()
    links = (
        sb.table("user_recipes")
        .select(f"saved_at,recipe_id,recipes({_RECIPE_SUMMARY_COLS})")
        .eq("user_id", str(user_id))
        .order("saved_at", desc=True)
        .execute()
    )
    recipes = [row.get("recipes") for row in (links.data or []) if row.get("recipes")]
    target = normalize_language(language_code)
    translations = get_recipe_translations(
        [UUID(str(recipe["id"])) for recipe in recipes if recipe.get("id")],
        target,
    )
    out: list[RecipeSummary] = []
    for row in links.data or []:
        recipe = row.get("recipes")
        saved_at = row.get("saved_at")
        if recipe and saved_at:
            recipe = dict(recipe)
            recipe_id = str(recipe.get("id") or "")
            if normalize_language(recipe.get("language_code")) != target:
                translation = translations.get(recipe_id)
                if translation and translation.get("source_fingerprint") == source_recipe_fingerprint(recipe):
                    recipe.update(translation.get("payload") or {})
                    recipe["language_code"] = target
            out.append(recipe_summary_from_row(recipe, saved_at=str(saved_at)))
    return out


def user_owns_recipe(user_id: UUID, recipe_id: UUID) -> bool:
    sb = get_supabase()
    res = (
        sb.table("user_recipes")
        .select("recipe_id")
        .eq("user_id", str(user_id))
        .eq("recipe_id", str(recipe_id))
        .limit(1)
        .execute()
    )
    return bool(res.data)


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
    language_code: str = "en-US",
    job_kind: str = "extract",
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
        "language_code": language_code,
        "job_kind": job_kind,
        "cache_hit": cache_hit,
        "cost_cents": cost_cents,
        "recipe_id": str(recipe_id) if recipe_id else None,
        "progress": 100 if status == "completed" else 0,
    }
    res = sb.table("extract_jobs").insert(payload).execute()
    row = res.data[0]
    return row


def update_job(job_id: UUID, **fields) -> dict | None:
    sb = get_supabase()
    clean = {k: (str(v) if isinstance(v, UUID) else v) for k, v in fields.items()}
    try:
        res = sb.table("extract_jobs").update(clean).eq("id", str(job_id)).execute()
    except Exception as exc:
        # Keep the web path usable during the additive lease rollout if the
        # application deploy briefly precedes migration 011/schema refresh.
        message = str(exc).lower()
        if "lease_until" not in message or "column" not in message:
            raise
        clean.pop("lease_until", None)
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


def get_active_job_for_user(*, user_id: UUID, source_url_norm: str, language_code: str = "en-US", job_kind: str = "extract") -> dict | None:
    # Kept as a compatibility helper for callers outside the API module.
    return get_active_job(source_url_norm=source_url_norm, language_code=language_code, job_kind=job_kind)


def get_active_job(*, source_url_norm: str, language_code: str = "en-US", job_kind: str = "extract", recipe_id: UUID | None = None) -> dict | None:
    sb = get_supabase()
    query = (
        sb.table("extract_jobs")
        .select("*")
        .eq("source_url_norm", source_url_norm)
        .eq("job_kind", job_kind)
        .in_("status", ["pending", "processing"])
    )
    if job_kind == "translation":
        if recipe_id is None:
            return None
        query = query.eq("recipe_id", str(recipe_id)).eq("language_code", normalize_language(language_code))
    res = query.order("created_at", desc=True).limit(1).execute()
    rows = res.data or []
    return rows[0] if rows else None


def grant_job_access(*, job_id: UUID, user_id: UUID) -> None:
    try:
        get_supabase().table("extract_job_access").upsert(
            {"job_id": str(job_id), "user_id": str(user_id)}
        ).execute()
    except Exception as exc:
        raise JobAccessUnavailable("Shared job access unavailable") from exc


def user_can_access_job(*, job_id: UUID, user_id: UUID, row: dict | None = None) -> bool:
    # Reuse a row already loaded by the endpoint when available. A second
    # read creates a needless race where a transient DB read can turn a valid
    # owner poll into a false 403.
    row = row or get_job(job_id)
    if row and str(row.get("user_id") or "") == str(user_id):
        return True
    try:
        res = get_supabase().table("extract_job_access").select("job_id").eq(
            "job_id", str(job_id)
        ).eq("user_id", str(user_id)).limit(1).execute()
        return bool(res.data)
    except Exception as exc:
        raise JobAccessUnavailable("Shared job access unavailable") from exc


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


def anonymize_user_data(user_id: UUID) -> None:
    """Remove personal request data before the auth profile is deleted."""
    sb = get_supabase()
    operations = (
        (
            "extract_jobs",
            {
                "user_id": None,
                "source_url_raw": "[deleted]",
                "source_url_norm": "[deleted]",
                "error": None,
            },
        ),
        ("usage_events", {"user_id": None}),
        ("api_spend_ledger", {"user_id": None}),
        ("security_events", {"user_id": None}),
    )
    for table, fields in operations:
        try:
            sb.table(table).update(fields).eq("user_id", str(user_id)).execute()
        except Exception:
            # Keep account deletion compatible during the additive migration rollout.
            continue


def week_start_utc() -> datetime:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start - timedelta(days=start.weekday())
