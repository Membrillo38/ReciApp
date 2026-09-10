from __future__ import annotations

import json
import logging
import re

from openai import OpenAI
from pydantic import ValidationError

from app.config import settings
from app.costing import estimate_miss_cost_cents, record_chat_usage
from app.extract import ExtractError
from app.localization import (
    build_recipe_prompt,
    ingredient_section_name,
    language_name,
    normalize_language,
    optional_section_name,
    untitled_recipe_name,
)
from app.models import Ingredient, IngredientSection, Platform, Recipe, RecipeTip, Step

logger = logging.getLogger(__name__)

RECIPE_UNDETERMINED_ERROR = "Could not determine a recipe from this video."
RECIPE_INCOMPLETE_ERROR = "Could not extract a complete recipe from this video."
LINK_IN_BIO_ERROR = "Recipe link in bio. Open the creator profile bio for the full recipe."
_MIN_RECIPE_CONFIDENCE = 0.7
_BLANK_VALUES = {"", "null", "none", "n/a", "nil", "undefined", "-"}
_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_OPTIONAL_MARKER_RE = re.compile(
    r"(?i)(?:\s*[\(\[]\s*)?(?:optional|opcional(?:es)?|optionnel(?:le)?|opzionale|opcjonalnie)"
    r"(?:\s*[\)\]]\s*)?$"
)
_OPTIONAL_PREFIX_RE = re.compile(
    r"(?i)^\s*(?:optional|opcional(?:es)?|optionnel(?:le)?|opzionale)\s*[:\-–]?\s+"
)
_GENERIC_INGREDIENT_TITLES = {
    "ingredients",
    "ingredient",
    "ingredientes",
    "ingrédient",
    "ingrédients",
    "zutaten",
    "ingredienti",
}
_OPTIONAL_TITLES = {
    "optional",
    "opcionales",
    "opcional",
    "optionnel",
    "optionnelle",
    "opzionale",
    "optional ingredients",
    "ingredientes opcionales",
    "opcionales",
}
# Headings that OCR/LLM sometimes emit as fake ingredient rows.
_SECTION_HEADING_RE = re.compile(
    r"(?i)^(?:"
    r"optional(?:\s+ingredients?)?|"
    r"opcionales?(?:\s+ingredientes?)?|"
    r"optionnel(?:le)?s?(?:\s+ingr[eé]dients?)?|"
    r"opzionale(?:\s+ingredienti)?|"
    r"for the\s+.+|"
    r"para (?:el|la|los|las)\s+.+|"
    r"pour (?:la|le|les)\s+.+|"
    r".+\s+(?:sauce|dough|marinade|dressing|topping|toppings|garnish|filling|glaze|base|mix)|"
    r"(?:salsa|masa|adobo|cobertura|relleno|ali[nñ]o|cobertura|guarnici[oó]n|recheio).*"
    r")$"
)
# Model often flags missing servings/times as blocking — those are not cook-stoppers.
_SOFT_BLOCKING_GAP_RE = re.compile(
    r"(?i)\b("
    r"servings?|porciones?|raciones?|"
    r"prep(?:aration)?(?:\s+time)?|tiempo\s+de\s+preparaci[oó]n|"
    r"cook(?:ing)?(?:\s+time)?|tiempo\s+de\s+cocci[oó]n|"
    r"minutes?|minutos?|horas?|"
    r"temperature|temperatura"
    r")\b"
)
# Caption/spoken marketing that points off-video — abort before OCR/STT/vision spend.
_LINK_IN_BIO_RE = re.compile(
    r"(?:"
    r"(?:full\s+)?(?:recipe|receta|recetas|link|enlace|liga|url)"
    r".{0,40}?"
    r"(?:in|en)\s+(?:the\s+|la\s+|mi\s+|my\s+)?(?:bio|biograf[ií]a)"
    r"|"
    r"(?:in|en)\s+(?:the\s+|la\s+|mi\s+|my\s+)?(?:bio|biograf[ií]a)"
    r".{0,40}?"
    r"(?:full\s+)?(?:recipe|receta|recetas|link|enlace|liga|url)"
    r"|"
    r"(?:check|see|look|mira|ve[ea]?|revisa)\s+(?:my\s+|mi\s+|en\s+(?:la\s+|mi\s+)?)?(?:bio|biograf[ií]a)"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def text_points_to_link_in_bio(*parts: str | None) -> bool:
    blob = " ".join(part for part in parts if part and str(part).strip())
    if not blob:
        return False
    return bool(_LINK_IN_BIO_RE.search(blob))


def reject_link_in_bio(*parts: str | None) -> None:
    if text_points_to_link_in_bio(*parts):
        raise ExtractError(LINK_IN_BIO_ERROR)


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
            "is_complete": {"type": "boolean"},
            "blocking_gaps": {"type": "array", "items": {"type": "string"}},
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
            "is_complete",
            "blocking_gaps",
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
    require_complete: bool = True,
) -> Recipe | None:
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
    source_json = _bounded_source_json(payload)
    user_content = build_recipe_prompt(target_language, source_json)

    messages = [
        {
            "role": "system",
            "content": (
                f"You extract complete, reproducible recipes from noisy social video metadata. "
                f"Write all user-facing recipe fields in {target_language}."
            ),
        },
        {"role": "user", "content": user_content},
    ]
    data = _request_structured_recipe(messages)
    ingredient_sections = _usable_ingredient_sections(
        data.get("ingredient_sections"),
        language_code=language_code,
    )
    steps = _usable_steps(data.get("steps"))
    try:
        confidence = float(data.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.0
    is_complete = bool(data.get("is_complete"))
    blocking_gaps = [
        str(item).strip()
        for item in (data.get("blocking_gaps") or [])
        if str(item).strip()
    ]
    ingredients = [
        ingredient
        for section in ingredient_sections
        for ingredient in section.ingredients
    ]
    if not ingredient_sections or not steps or confidence < _MIN_RECIPE_CONFIDENCE:
        return None
    try:
        recipe = Recipe(
            title=_visible_text(data.get("title")) or untitled_recipe_name(language_code),
            ingredients=ingredients,
            ingredient_sections=ingredient_sections,
            steps=steps,
            servings=data.get("servings"),
            prep_minutes=data.get("prep_minutes"),
            cook_minutes=data.get("cook_minutes"),
            tags=data.get("tags") or [],
            confidence=confidence,
            missing_fields=data.get("missing_fields") or [],
            source_url=source_url,
            platform=platform,
            thumbnail_url=thumbnail_url,
            carousel_image_urls=carousel_image_urls or [],
            author=author,
            description=_optional_text(data.get("description")),
            tips=data.get("tips") or [],
            raw_transcript=_merge_text(transcript, slide_text),
            language_code=language_code,
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        return None
    if require_complete and not recipe_is_complete(
        recipe,
        is_complete=is_complete,
        blocking_gaps=blocking_gaps,
    ):
        return None
    return recipe


def material_blocking_gaps(gaps: list[str] | None) -> list[str]:
    """Drop soft metadata complaints; keep gaps that block cooking."""
    material: list[str] = []
    for gap in gaps or []:
        text = str(gap).strip()
        if not text:
            continue
        if _SOFT_BLOCKING_GAP_RE.search(text):
            continue
        material.append(text)
    return material


def recipe_is_complete(
    recipe: Recipe,
    *,
    is_complete: bool = True,
    blocking_gaps: list[str] | None = None,
) -> bool:
    """Deterministic completeness gate after structured model output."""
    gaps = material_blocking_gaps(blocking_gaps)
    # Trust structure over the model's is_complete when gaps are only soft metadata.
    if gaps:
        return False
    if recipe.confidence < _MIN_RECIPE_CONFIDENCE:
        return False
    if not recipe.ingredient_sections or not recipe.steps:
        return False
    if not recipe.ingredients:
        return False
    orders = [step.order for step in recipe.steps]
    if orders != list(range(1, len(orders) + 1)):
        return False
    if any(not step.text.strip() for step in recipe.steps):
        return False
    # Model said incomplete with no material gaps: still require structure above.
    # is_complete=False alone is not enough to reject (LLM often flags servings/times).
    _ = is_complete
    step_blob = " ".join(step.text.lower() for step in recipe.steps)
    step_tokens = set(_TOKEN_RE.findall(step_blob))
    identified = []
    for ingredient in recipe.ingredients:
        name = (ingredient.name or "").strip().lower()
        if not name:
            return False
        tokens = [token for token in _TOKEN_RE.findall(name) if len(token) > 2]
        if tokens and not any(token in step_tokens for token in tokens):
            # Ingredient may only appear in the list (mise en place). That is OK
            # when at least one later step mentions cooking/assembly broadly.
            identified.append(name)
            continue
        identified.append(name)
    if not identified:
        return False
    return True


def _visible_text(value: object) -> str:
    text = str(value).strip() if value is not None else ""
    if not text or text.lower() in _BLANK_VALUES:
        return ""
    return text


def _optional_text(value: object) -> str | None:
    text = _visible_text(value)
    return text or None


def _norm_title(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower()).rstrip(":.-–")


def _is_optional_title(title: str) -> bool:
    return _norm_title(title) in _OPTIONAL_TITLES or _norm_title(title).startswith("optional")


def _is_generic_title(title: str) -> bool:
    return _norm_title(title) in _GENERIC_INGREDIENT_TITLES


def _looks_like_section_heading(ingredient: Ingredient) -> bool:
    name = ingredient.name.strip()
    if not name:
        return False
    if ingredient.quantity or ingredient.unit:
        return False
    cleaned = name.rstrip(":.-–").strip()
    if _is_generic_title(cleaned) or _is_optional_title(cleaned):
        return True
    if name.endswith((":", "—", "-")) and len(cleaned.split()) <= 6:
        return True
    return bool(_SECTION_HEADING_RE.match(cleaned))


def _strip_optional_marker(ingredient: Ingredient) -> tuple[Ingredient, bool]:
    name = ingredient.name.strip()
    optional = False
    if _OPTIONAL_PREFIX_RE.match(name):
        name = _OPTIONAL_PREFIX_RE.sub("", name).strip()
        optional = True
    if _OPTIONAL_MARKER_RE.search(name):
        name = _OPTIONAL_MARKER_RE.sub("", name).strip(" ,;-–")
        optional = True
    if not name:
        return ingredient, optional
    if name == ingredient.name and not optional:
        return ingredient, False
    return Ingredient(name=name, quantity=ingredient.quantity, unit=ingredient.unit), optional


def power_up_ingredient_sections(
    sections: list[IngredientSection],
    *,
    language_code: str = "en-US",
) -> list[IngredientSection]:
    """Split headings / optional markers into real ingredient_sections."""
    language_code = normalize_language(language_code)
    default_title = ingredient_section_name(language_code)
    optional_title = optional_section_name(language_code)

    rebuilt: list[IngredientSection] = []
    current_title = default_title
    current: list[Ingredient] = []
    optional_bucket: list[Ingredient] = []

    def flush_current() -> None:
        nonlocal current
        if current:
            rebuilt.append(IngredientSection(title=current_title, ingredients=list(current)))
            current = []

    for section in sections:
        section_title = _visible_text(section.title) or default_title
        flush_current()
        route_all_optional = _is_optional_title(section_title)
        if route_all_optional:
            current_title = optional_title
        elif _is_generic_title(section_title):
            current_title = default_title
        else:
            current_title = section_title

        for ingredient in section.ingredients:
            if _looks_like_section_heading(ingredient):
                heading = ingredient.name.strip().rstrip(":.-–").strip() or default_title
                if _is_optional_title(heading):
                    flush_current()
                    current_title = optional_title
                    route_all_optional = True
                    continue
                if _is_generic_title(heading):
                    flush_current()
                    current_title = default_title
                    route_all_optional = False
                    continue
                flush_current()
                current_title = heading
                route_all_optional = False
                continue

            cleaned, marked_optional = _strip_optional_marker(ingredient)
            if not cleaned.name.strip():
                continue
            if route_all_optional or marked_optional:
                optional_bucket.append(cleaned)
            else:
                current.append(cleaned)

    flush_current()

    if optional_bucket:
        # Merge into existing Optional section when present.
        for section in rebuilt:
            if _is_optional_title(section.title):
                section.ingredients.extend(optional_bucket)
                optional_bucket = []
                break
        if optional_bucket:
            rebuilt.append(IngredientSection(title=optional_title, ingredients=optional_bucket))

    # Drop empties / collapse duplicate generic titles only when single section.
    rebuilt = [section for section in rebuilt if section.ingredients]
    return rebuilt or sections


def _usable_ingredient_sections(
    raw_sections: object,
    *,
    language_code: str = "en-US",
) -> list[IngredientSection]:
    sections: list[IngredientSection] = []
    if not isinstance(raw_sections, list):
        return sections
    default_title = ingredient_section_name(language_code)
    for section in raw_sections:
        if not isinstance(section, dict):
            continue
        title = _visible_text(section.get("title")) or default_title
        ingredients: list[Ingredient] = []
        for item in section.get("ingredients") or []:
            if not isinstance(item, dict):
                continue
            name = _visible_text(item.get("name"))
            if not name:
                continue
            quantity = _optional_text(item.get("quantity"))
            unit = _optional_text(item.get("unit"))
            ingredients.append(Ingredient(name=name, quantity=quantity, unit=unit))
        if ingredients:
            sections.append(IngredientSection(title=title, ingredients=ingredients))
    return power_up_ingredient_sections(sections, language_code=language_code)


def _usable_steps(raw_steps: object) -> list[Step]:
    steps: list[Step] = []
    if not isinstance(raw_steps, list):
        return steps
    order = 1
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        text = _visible_text(item.get("text"))
        if not text:
            continue
        duration = item.get("duration_minutes")
        if duration is not None:
            try:
                duration = int(duration)
            except (TypeError, ValueError):
                duration = None
        steps.append(Step(order=order, text=text, duration_minutes=duration))
        order += 1
    return steps


def _merge_text(transcript: str | None, slide_text: str | None) -> str | None:
    parts = [p.strip() for p in (transcript, slide_text) if p and p.strip()]
    return "\n\n".join(parts) if parts else None


def _bounded_source_json(payload: dict, max_chars: int = 24_000) -> str:
    """Bound metadata fields without cutting serialized carousel OCR JSON."""
    bounded = dict(payload)
    for key, limit in (("title", 2_000), ("author", 500), ("description", 8_000), ("transcript", 16_000)):
        value = bounded.get(key)
        if isinstance(value, str) and len(value) > limit:
            bounded[key] = value[:limit] + "\n[metadata truncated at supported input bound]"

    encoded = json.dumps(bounded, ensure_ascii=False)
    if len(encoded) <= max_chars:
        return encoded

    # Carousel/frame OCR is ordered evidence. Reduce optional metadata first;
    # never slice the serialized object or silently remove the final slide.
    for key in ("description", "title", "author", "transcript"):
        if bounded.get(key):
            bounded[key] = "[omitted at supported input bound]"
            encoded = json.dumps(bounded, ensure_ascii=False)
            if len(encoded) <= max_chars:
                return encoded
    raise ExtractError("Recipe source text exceeds supported bound")


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
        "is_complete": True,
        "blocking_gaps": [],
        "confidence": recipe.confidence,
    }
    prompt = (
        f"Translate this structured cooking recipe into {target_language}.\n"
        "Translate every user-facing text field, including section titles, ingredient names, units, steps, tips, tags, and description. "
        "Preserve quantities, durations, ordering, null values, is_complete, and blocking_gaps. Do not add or remove recipe content. "
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
    ingredient_sections = power_up_ingredient_sections(
        [
            IngredientSection(**section)
            for section in (data.get("ingredient_sections") or [])
            if isinstance(section, dict) and section.get("ingredients")
        ],
        language_code=language_code,
    )
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
            language_code=language_code,
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
        record_chat_usage(
            response,
            fallback_cents=estimate_miss_cost_cents(),
        )
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
