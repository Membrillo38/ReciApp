from __future__ import annotations

import json
import logging

from openai import OpenAI
from pydantic import ValidationError

from app.config import settings
from app.extract import ExtractError, MediaInfo
from app.localization import build_recipe_prompt, language_name, normalize_language, untitled_recipe_name
from app.models import Ingredient, IngredientSection, Platform, Recipe, RecipeTip, Step

logger = logging.getLogger(__name__)


RECIPE_SCHEMA = {
    "name": "recipe",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "title": {"type": "string"},
            "description": {"type": ["string", "null"]},
            "ingredient_sections": {
                "type": "array",
                "items": {
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
                    },
                    "required": ["title", "ingredients"],
                },
            },
            "tips": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "title": {"type": ["string", "null"]},
                        "text": {"type": "string"},
                    },
                    "required": ["title", "text"],
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
            "description",
            "ingredient_sections",
            "tips",
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
    language_code: str = "en-US",
    carousel_image_urls: list[str] | None = None,
) -> Recipe:
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")

    language_code = normalize_language(language_code)
    target_language = language_name(language_code)
    payload = {
        "platform": platform.value,
        "title": title,
        "description": description,
        "author": author,
        "slide_text": slide_text,
        "transcript": transcript,
    }
    # Bound source size to keep prompt and output costs predictable.
    source_json = json.dumps(payload, ensure_ascii=False)
    # Carousel OCR is ordered by slide; keep it ahead of optional video
    # transcript so later ingredient/step slides survive the bound.
    source_json = source_json[:24000]
    user_content = build_recipe_prompt(target_language, source_json)

    messages = [
        {
            "role": "system",
            "content": f"You extract recipes from noisy social video metadata. Write all user-facing recipe fields in {target_language}.",
        },
        {"role": "user", "content": user_content},
    ]
    data = _request_structured_recipe(messages)

    ingredient_sections = [
        IngredientSection(**section)
        for section in (data.get("ingredient_sections") or [])
        if section.get("ingredients")
    ]
    ingredients = [
        ingredient
        for section in ingredient_sections
        for ingredient in section.ingredients
    ]

    try:
        return Recipe(
            title=data["title"] or untitled_recipe_name(language_code),
            ingredients=ingredients,
            ingredient_sections=ingredient_sections,
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
            carousel_image_urls=carousel_image_urls or [],
            author=author,
            description=data.get("description") or None,
            tips=data.get("tips") or [],
            raw_transcript=_merge_text(transcript, slide_text),
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ExtractError("Recipe output failed validation") from exc


def _merge_text(transcript: str | None, slide_text: str | None) -> str | None:
    parts = [p.strip() for p in (transcript, slide_text) if p and p.strip()]
    return "\n\n".join(parts) if parts else None


def translate_recipe(recipe: Recipe, target_language_code: str) -> Recipe:
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")

    language_code = normalize_language(target_language_code)
    target_language = language_name(language_code)
    source = {
        "title": recipe.title,
        "description": recipe.description,
        "ingredient_sections": [section.model_dump() for section in recipe.ingredient_sections],
        "steps": [step.model_dump() for step in recipe.steps],
        "servings": recipe.servings,
        "prep_minutes": recipe.prep_minutes,
        "cook_minutes": recipe.cook_minutes,
        "tags": recipe.tags,
        "missing_fields": recipe.missing_fields,
        "tips": [tip.model_dump() for tip in recipe.tips],
    }
    prompt = (
        f"Translate this structured cooking recipe into {target_language}.\n"
        "Translate every user-facing text field, including section titles, ingredient names, units, steps, tips, tags, and description. "
        "Preserve quantities, durations, ordering, and null values. Do not add or remove recipe content. "
        "Return the same JSON structure.\n\n"
        f"RECIPE:\n{json.dumps(source, ensure_ascii=False)}"
    )
    messages = [
        {
            "role": "system",
            "content": f"You translate structured recipes accurately into {target_language}. Return only valid JSON.",
        },
        {"role": "user", "content": prompt[:16000]},
    ]
    data = _request_structured_recipe(messages)
    ingredient_sections = [
        IngredientSection(**section)
        for section in (data.get("ingredient_sections") or [])
        if section.get("ingredients")
    ]
    ingredients = [ingredient for section in ingredient_sections for ingredient in section.ingredients]
    try:
        return Recipe(
            id=recipe.id,
            title=data["title"] or untitled_recipe_name(language_code),
            ingredients=ingredients,
            ingredient_sections=ingredient_sections,
            steps=[Step(**step) for step in data.get("steps") or []],
            servings=data.get("servings"),
            prep_minutes=data.get("prep_minutes"),
            cook_minutes=data.get("cook_minutes"),
            tags=data.get("tags") or [],
            confidence=recipe.confidence,
            missing_fields=data.get("missing_fields") or recipe.missing_fields,
            source_url=recipe.source_url,
            platform=recipe.platform,
            thumbnail_url=recipe.thumbnail_url,
            carousel_image_urls=recipe.carousel_image_urls,
            author=recipe.author,
            description=data.get("description") or None,
            tips=[RecipeTip(**tip) for tip in data.get("tips") or []],
            raw_transcript=recipe.raw_transcript,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise ExtractError("Translated recipe output failed validation") from exc


def _request_structured_recipe(messages: list[dict]) -> dict:
    client = OpenAI(api_key=settings.openai_api_key)
    last_error: Exception | None = None
    for attempt, max_tokens in enumerate((2400, 4000)):
        logger.info("recipe_model attempt=%d max_tokens=%d", attempt + 1, max_tokens)
        request_messages = messages
        if attempt:
            # A shorter retry leaves room for the schema envelope when source
            # metadata is unusually large or noisy.
            request_messages = [dict(message) for message in messages]
            if len(request_messages) > 1 and isinstance(request_messages[1].get("content"), str):
                request_messages[1]["content"] = request_messages[1]["content"][:8000]
        try:
            response = client.chat.completions.create(
                model=settings.recipe_model,
                messages=request_messages,
                response_format={"type": "json_schema", "json_schema": RECIPE_SCHEMA},
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.warning("recipe_model attempt=%d error_type=%s", attempt + 1, type(exc).__name__)
            last_error = exc
            continue
        choices = getattr(response, "choices", None) or []
        if not choices:
            last_error = ExtractError("Recipe model returned no choices")
            continue
        choice = choices[0]
        message = getattr(choice, "message", None)
        if getattr(message, "refusal", None):
            last_error = ExtractError("Recipe model refused to translate this recipe")
            continue
        raw = getattr(message, "content", None)
        if not raw:
            last_error = ExtractError("Recipe model returned empty response")
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if choice.finish_reason == "length" and max_tokens < 4000:
            continue
        if not isinstance(data, dict):
            raise ExtractError("Recipe model returned invalid structured output")
        return data
    raise ExtractError("Recipe model temporarily unavailable or returned invalid output") from last_error
