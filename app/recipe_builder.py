from __future__ import annotations

import json

from openai import OpenAI

from app.config import settings
from app.extract import ExtractError, MediaInfo
from app.models import Platform, Recipe


RECIPE_SCHEMA = {
    "name": "recipe",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "ingredients": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "name": {"type": "string"},
                        "quantity": {"type": ["string", "null"]},
                        "unit": {"type": ["string", "null"]},
                    },
                    "required": ["name", "quantity", "unit"],
                },
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "order": {"type": "integer"},
                        "text": {"type": "string"},
                        "duration_minutes": {"type": ["integer", "null"]},
                    },
                    "required": ["order", "text", "duration_minutes"],
                },
            },
            "servings": {"type": ["integer", "null"]},
            "prep_minutes": {"type": ["integer", "null"]},
            "cook_minutes": {"type": ["integer", "null"]},
            "tags": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number"},
            "missing_fields": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "title",
            "ingredients",
            "steps",
            "servings",
            "prep_minutes",
            "cook_minutes",
            "tags",
            "confidence",
            "missing_fields",
        ],
    },
}


def build_recipe(
    *,
    platform: Platform,
    source_url: str,
    title: str,
    description: str,
    author: str | None,
    thumbnail_url: str | None,
    transcript: str | None,
    slide_text: str | None,
) -> Recipe:
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")

    payload = {
        "platform": platform.value,
        "title": title,
        "description": description,
        "author": author,
        "transcript": transcript,
        "slide_text": slide_text,
    }
    # Bound source size to keep prompt and output costs predictable.
    source_json = json.dumps(payload, ensure_ascii=False)
    source_json = source_json[:12000]
    user_content = (
        "Turn the following social video content into a structured cooking recipe.\n"
        "Use Spanish for step text when source is Spanish; otherwise keep source language.\n"
        "If quantities are missing, set quantity/unit null and list field in missing_fields.\n"
        "Do not invent ingredients not supported by the source text.\n\n"
        f"SOURCE:\n{source_json}"
    )

    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.recipe_model,
        messages=[
            {
                "role": "system",
                "content": "You extract recipes from noisy social video metadata.",
            },
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_schema", "json_schema": RECIPE_SCHEMA},
        max_tokens=900,
    )

    raw = response.choices[0].message.content
    if not raw:
        raise ExtractError("Recipe model returned empty response")

    data = json.loads(raw)
    return Recipe(
        title=data["title"] or title or "Receta sin título",
        ingredients=data["ingredients"],
        steps=data["steps"],
        servings=data.get("servings"),
        prep_minutes=data.get("prep_minutes"),
        cook_minutes=data.get("cook_minutes"),
        tags=data.get("tags") or [],
        confidence=float(data.get("confidence") or 0.5),
        missing_fields=data.get("missing_fields") or [],
        source_url=source_url,
        platform=platform,
        thumbnail_url=thumbnail_url,
        author=author,
        description=description or None,
        raw_transcript=_merge_text(transcript, slide_text),
    )


def _merge_text(transcript: str | None, slide_text: str | None) -> str | None:
    parts = [p.strip() for p in (transcript, slide_text) if p and p.strip()]
    return "\n\n".join(parts) if parts else None
