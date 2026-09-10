from __future__ import annotations

import hashlib
import json
from uuid import UUID

from app.db import execute_returning, fetch_all, fetch_one
from app.localization import ingredient_section_name, normalize_language
from app.models import Recipe


def get_recipe_translation(
    recipe_id: UUID,
    language_code: str,
    *,
    source_fingerprint: str | None = None,
) -> dict | None:
    code = normalize_language(language_code)
    row = fetch_one(
        """
        select * from recipe_translations
         where recipe_id = %s and language_code = %s
         limit 1
        """,
        (recipe_id, code),
    )
    if not row:
        return None
    if source_fingerprint and row.get("source_fingerprint") != source_fingerprint:
        return None
    return row


def get_recipe_translations(recipe_ids: list[UUID], language_code: str) -> dict[str, dict]:
    if not recipe_ids:
        return {}
    code = normalize_language(language_code)
    rows = fetch_all(
        """
        select recipe_id, payload, source_fingerprint
          from recipe_translations
         where recipe_id = any(%s) and language_code = %s
        """,
        (recipe_ids, code),
    )
    return {str(row["recipe_id"]): row for row in rows if row.get("recipe_id")}


def upsert_recipe_translation(
    recipe_id: UUID,
    language_code: str,
    payload: dict,
    *,
    source_fingerprint: str | None = None,
) -> dict:
    code = normalize_language(language_code)
    data = {
        "recipe_id": str(recipe_id),
        "language_code": code,
        "payload": payload,
        "source_fingerprint": source_fingerprint or translation_fingerprint(payload),
    }
    return execute_returning(
        """
        insert into recipe_translations (recipe_id, language_code, payload, source_fingerprint)
        values (%s, %s, %s, %s)
        on conflict (recipe_id, language_code) do update
           set payload = excluded.payload,
               source_fingerprint = excluded.source_fingerprint
        returning *
        """,
        (data["recipe_id"], data["language_code"], data["payload"], data["source_fingerprint"]),
    ) or data


def translation_fingerprint(payload: dict) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def recipe_translation_payload(recipe: Recipe) -> dict:
    return {
        "title": recipe.title,
        "description": recipe.description,
        "ingredient_sections": [section.model_dump() for section in recipe.ingredient_sections],
        "steps": [step.model_dump() for step in recipe.steps],
        "tags": recipe.tags,
        "missing_fields": recipe.missing_fields,
        "tips": [tip.model_dump() for tip in recipe.tips],
    }


def source_recipe_fingerprint(row: dict) -> str:
    sections = row.get("ingredient_sections") or []
    if not sections and row.get("ingredients"):
        sections = [{
            "title": ingredient_section_name(row.get("language_code")),
            "ingredients": row.get("ingredients") or [],
        }]
    return translation_fingerprint({
        "title": row.get("title"),
        "description": row.get("description"),
        "ingredient_sections": sections,
        "steps": row.get("steps") or [],
        "servings": row.get("servings"),
        "prep_minutes": row.get("prep_minutes"),
        "cook_minutes": row.get("cook_minutes"),
        "tags": row.get("tags") or [],
        "missing_fields": row.get("missing_fields") or [],
        "tips": row.get("tips") or [],
    })


def localized_recipe_row(base_row: dict, language_code: str) -> dict | None:
    code = normalize_language(language_code)
    base_code = normalize_language(base_row.get("language_code"))
    if base_code == code:
        row = dict(base_row)
        row["language_code"] = code
        return row

    translation = get_recipe_translation(
        UUID(str(base_row["id"])),
        code,
        source_fingerprint=source_recipe_fingerprint(base_row),
    )
    if not translation:
        return None
    payload = translation.get("payload") or {}
    row = dict(base_row)
    row.update(payload)
    row["language_code"] = code
    return row
