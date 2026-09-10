from __future__ import annotations

SUPPORTED_LANGUAGE_CODES: tuple[str, ...] = ("en-US", "es-ES", "fr-FR", "de", "it", "pt-BR")

LANGUAGE_NAMES: dict[str, str] = {
    "en-US": "English",
    "es-ES": "Spanish",
    "fr-FR": "French",
    "de": "German",
    "it": "Italian",
    "pt-BR": "Portuguese",
}

UNTITLED_RECIPE_NAMES: dict[str, str] = {
    "en-US": "Untitled recipe",
    "es-ES": "Receta sin título",
    "fr-FR": "Recette sans titre",
    "de": "Rezept ohne Titel",
    "it": "Ricetta senza titolo",
    "pt-BR": "Receita sem título",
}

INGREDIENT_SECTION_NAMES: dict[str, str] = {
    "en-US": "Ingredients",
    "es-ES": "Ingredientes",
    "fr-FR": "Ingrédients",
    "de": "Zutaten",
    "it": "Ingredienti",
    "pt-BR": "Ingredientes",
}

OPTIONAL_SECTION_NAMES: dict[str, str] = {
    "en-US": "Optional",
    "es-ES": "Opcional",
    "fr-FR": "Optionnel",
    "de": "Optional",
    "it": "Opzionale",
    "pt-BR": "Opcional",
}


def normalize_language(value: str | None) -> str:
    """Return one canonical allowlisted locale."""
    raw = (value or "").strip().replace("_", "-")
    if raw in SUPPORTED_LANGUAGE_CODES:
        return raw
    lowered = raw.lower()
    for code in SUPPORTED_LANGUAGE_CODES:
        if code.lower() == lowered:
            return code
    base = lowered.split("-", 1)[0]
    return {
        "en": "en-US",
        "es": "es-ES",
        "fr": "fr-FR",
        "de": "de",
        "it": "it",
        "pt": "pt-BR",
    }.get(base, "en-US")


def language_name(code: str) -> str:
    return LANGUAGE_NAMES[normalize_language(code)]


def untitled_recipe_name(code: str) -> str:
    return UNTITLED_RECIPE_NAMES[normalize_language(code)]


def ingredient_section_name(code: str) -> str:
    return INGREDIENT_SECTION_NAMES[normalize_language(code)]


def optional_section_name(code: str) -> str:
    return OPTIONAL_SECTION_NAMES[normalize_language(code)]


def build_recipe_prompt(target_language: str, source_json: str) -> str:
    return (
        "Turn the following social video content into a structured cooking recipe.\n"
        f"Write title, description, ingredient names, units, steps, tips, tags, missing_fields, "
        f"and blocking_gaps in {target_language}.\n"
        "Keep proper names, platform names, URLs, and author names unchanged.\n"
        "Merge ALL evidence: description, metadata, captions/subtitles, spoken transcript, and "
        "on-screen visual notes. Prefer precise overlay quantities when the same ingredient appears "
        "in multiple sources. Do not drop spoken-only or overlay-only ingredients.\n"
        "If quantities are missing from the evidence, set quantity/unit null and list the field in "
        "missing_fields. Missing quantities alone do NOT make the recipe incomplete.\n"
        "Group ingredients into the distinct components or headings present in the source, such as "
        "'Parmesan Chicken', 'Creamy Sauce', 'Dough', 'Filling', or the localized equivalent of "
        "'Optional'. Keep each ingredient in its original component; do not merge separate "
        "components into one flat list. Headings like 'Optional', 'Opcional', 'For the sauce', "
        "'Para la salsa', or 'Toppings' MUST become their own ingredient_sections entries. "
        "Never leave an optional list inside the main Ingredients section. If an ingredient is "
        "marked optional inline (e.g. 'cheese (optional)'), put it in the Optional section and "
        "strip the optional marker from the name. If no headings are supported, use one section "
        "named with the localized equivalent of 'Ingredients'.\n"
        "Write cumulative steps: each step must assume everything that already happened, keep "
        "prior ingredients/preparations/state in context, and stay in chronological order. "
        "Do not emit isolated steps that ignore earlier work.\n"
        "Include times and temperatures only when the evidence states them.\n"
        "Extract separate actionable tips from the source, including storage, reheating, serving, "
        "or substitutions. Do not duplicate method steps as tips. Use an empty tips list when none exist.\n"
        "slide_text is on-screen overlay OCR / visual analysis notes. transcript is spoken audio or captions.\n"
        "Do not treat marketing captions as a complete ingredient list when overlay or transcript lists ingredients.\n"
        "Never invent ingredients, quantities, tips, temperatures, times, or steps that cannot be "
        "reasonably deduced from the evidence.\n"
        "Set is_complete true only when a cook can reproduce the full dish from this recipe alone: "
        "all used ingredients identified, available quantities preserved, steps ordered and coherent, "
        "no unexplained disappearing ingredients, and no missing necessary actions between steps. "
        "List every blocking gap in blocking_gaps when is_complete is false.\n"
        "If the source does not contain a real cooking recipe with ingredients and a method, return "
        "empty ingredient_sections, empty steps, confidence 0, is_complete false, and blocking_gaps "
        "explaining why. Do not invent a recipe from a title, marketing caption, or hashtags.\n\n"
        f"SOURCE:\n{source_json}"
    )
