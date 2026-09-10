from pathlib import Path
from uuid import uuid4

from app.models import Ingredient, IngredientSection, Platform, Recipe, RecipeTip, Step
from app.translation_cache import recipe_translation_payload


ROOT = Path(__file__).parents[1]


def test_translation_cache_is_global_and_language_keyed():
    migration = (ROOT / "supabase" / "migrations" / "008_recipe_translations.sql").read_text()
    expanded = (ROOT / "supabase" / "migrations" / "016_app_store_languages.sql").read_text()
    cache = (ROOT / "app" / "translation_cache.py").read_text()
    assert "create table if not exists public.recipe_translations" in migration
    assert "primary key (recipe_id, language_code)" in migration
    assert "user_id" not in migration
    assert "zh-Hans" in expanded and "pt-PT" in expanded
    assert "where recipe_id = %s and language_code = %s" in cache
    assert "on conflict (recipe_id, language_code)" in cache


def test_extract_flow_joins_shared_translation_jobs():
    main = (ROOT / "app" / "main.py").read_text()
    pipeline = (ROOT / "app" / "pipeline.py").read_text()
    assert "localized_recipe_row(cached, language_code)" in main
    assert 'job_kind="translation"' in main
    assert "run_translation_job" in main
    assert "upsert_recipe_translation" in pipeline


def test_translation_payload_keeps_structured_recipe_data():
    recipe = Recipe(
        id=uuid4(),
        title="Pasta",
        ingredients=[Ingredient(name="tomato", quantity="4", unit="units")],
        ingredient_sections=[
            IngredientSection(
                title="Sauce",
                ingredients=[Ingredient(name="tomato", quantity="4", unit="units")],
            )
        ],
        steps=[Step(order=1, text="Cook", duration_minutes=12)],
        servings=2,
        prep_minutes=5,
        cook_minutes=12,
        tags=["quick"],
        source_url="https://example.com/recipe",
        platform=Platform.youtube,
        tips=[RecipeTip(title="Storage", text="Keep chilled")],
        language_code="en-US",
    )
    payload = recipe_translation_payload(recipe)
    assert payload["title"] == "Pasta"
    assert payload["ingredient_sections"][0]["ingredients"][0]["quantity"] == "4"
    assert "ingredients" not in payload
    assert payload["steps"][0]["duration_minutes"] == 12
    assert payload["tips"][0]["text"] == "Keep chilled"
