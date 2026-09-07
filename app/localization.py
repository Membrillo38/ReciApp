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


def build_recipe_prompt(target_language: str, source_json: str) -> str:
    return (
        "Turn the following social video content into a structured cooking recipe.\n"
        f"Write title, description, ingredient names, units, steps, tips, tags, and missing_fields in {target_language}.\n"
        "Keep proper names, platform names, URLs, and author names unchanged.\n"
        "If quantities are missing, set quantity/unit null and list field in missing_fields.\n"
        "Group ingredients into the distinct components or headings present in the source, such as "
        "'Parmesan Chicken' and 'Creamy Sauce'. Keep each ingredient in its original component; "
        "do not merge separate components. If no headings are supported, use one section named with the localized equivalent of 'Ingredients'.\n"
        "Extract separate actionable tips from the source, including storage, reheating, serving, "
        "or substitutions. Do not duplicate method steps as tips. Use an empty tips list when none exist.\n"
        "Do not invent ingredients, tips, or sections not supported by the source text.\n\n"
        f"SOURCE:\n{source_json}"
    )
