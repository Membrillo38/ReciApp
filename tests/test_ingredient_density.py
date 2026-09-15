"""Contract tests for ingredient density_g_per_ml."""

from __future__ import annotations

from uuid import uuid4

from app.ingredient_density import parse_density_g_per_ml, resolve_density_g_per_ml
from app.models import Ingredient, IngredientSection, Platform, Recipe, RecipeTip, Step
from app.recipe_builder import (
    RECIPE_SCHEMA,
    _restore_quantity_and_density,
    _usable_ingredient_sections,
)
from app.store import recipe_public_from_row
from app.translation_cache import recipe_translation_payload, translation_fingerprint


def test_salt_and_flour_get_distinct_culinary_densities():
    sections = _usable_ingredient_sections(
        [
            {
                "title": "Ingredients",
                "ingredients": [
                    {"name": "salt", "quantity": "0.5", "unit": "cup", "density_g_per_ml": None},
                    {
                        "name": "all-purpose flour",
                        "quantity": "0.5",
                        "unit": "cup",
                        "density_g_per_ml": None,
                    },
                ],
            }
        ],
        language_code="en-US",
    )
    by_name = {item.name: item for section in sections for item in section.ingredients}
    assert by_name["salt"].density_g_per_ml == 1.2
    assert by_name["all-purpose flour"].density_g_per_ml == 0.53
    # Same volume must not collapse to equal mass via shared density.
    assert by_name["salt"].density_g_per_ml != by_name["all-purpose flour"].density_g_per_ml


def test_density_absent_when_unknown_or_countable():
    assert resolve_density_g_per_ml("mystery spice blend", quantity="1", unit="cup") is None
    assert resolve_density_g_per_ml("egg", quantity="2", unit="large") is None
    assert resolve_density_g_per_ml("garlic", quantity="2", unit="cloves") is None
    assert resolve_density_g_per_ml("salt", quantity="to taste", unit=None) is None

    sections = _usable_ingredient_sections(
        [
            {
                "title": "Ingredients",
                "ingredients": [
                    {"name": "egg", "quantity": "2", "unit": "large", "density_g_per_ml": 1.0},
                    {"name": "vanilla", "quantity": "to taste", "unit": None, "density_g_per_ml": 0.9},
                ],
            }
        ],
        language_code="en-US",
    )
    items = [item for section in sections for item in section.ingredients]
    assert all(item.density_g_per_ml is None for item in items)


def test_parse_density_rejects_zero_and_negative():
    assert parse_density_g_per_ml(None) is None
    assert parse_density_g_per_ml(0) is None
    assert parse_density_g_per_ml(-1.2) is None
    assert parse_density_g_per_ml("nope") is None
    assert parse_density_g_per_ml(0.53) == 0.53
    assert Ingredient(name="flour", density_g_per_ml=0).density_g_per_ml is None
    assert Ingredient(name="flour", density_g_per_ml=-3).density_g_per_ml is None


def test_model_invented_density_ignored_without_table_match():
    sections = _usable_ingredient_sections(
        [
            {
                "title": "Ingredients",
                "ingredients": [
                    {
                        "name": "exotic powder",
                        "quantity": "1",
                        "unit": "cup",
                        "density_g_per_ml": 9.99,
                    }
                ],
            }
        ],
        language_code="en-US",
    )
    assert sections[0].ingredients[0].density_g_per_ml is None


def test_translation_restore_keeps_quantity_and_density_numbers():
    source = [
        IngredientSection(
            title="Ingredients",
            ingredients=[
                Ingredient(name="salt", quantity="0.5", unit="cup", density_g_per_ml=1.2),
                Ingredient(
                    name="all-purpose flour",
                    quantity="0.5",
                    unit="cup",
                    density_g_per_ml=0.53,
                ),
            ],
        )
    ]
    translated = [
        IngredientSection(
            title="Ingredientes",
            ingredients=[
                Ingredient(name="sal", quantity="1/2", unit="taza", density_g_per_ml=2.0),
                Ingredient(name="harina", quantity="medio", unit="taza", density_g_per_ml=None),
            ],
        )
    ]
    restored = _restore_quantity_and_density(source, translated)
    items = restored[0].ingredients
    assert items[0].name == "sal"
    assert items[0].quantity == "0.5"
    assert items[0].density_g_per_ml == 1.2
    assert items[1].quantity == "0.5"
    assert items[1].density_g_per_ml == 0.53


def test_legacy_recipe_without_density_stays_compatible():
    recipe = recipe_public_from_row(
        {
            "id": str(uuid4()),
            "title": "Legacy",
            "ingredients": [{"name": "flour", "quantity": "1", "unit": "cup"}],
            "steps": [],
            "platform": "tiktok",
            "source_url_raw": "https://www.tiktok.com/@cook/video/legacy",
        }
    )
    assert recipe.ingredients[0].density_g_per_ml is None
    assert recipe.ingredient_sections[0].ingredients[0].density_g_per_ml is None


def test_schema_and_payload_include_density():
    ingredient_props = RECIPE_SCHEMA["schema"]["properties"]["ingredient_sections"]["items"][
        "properties"
    ]["ingredients"]["items"]["properties"]
    assert "density_g_per_ml" in ingredient_props
    assert "density_g_per_ml" in RECIPE_SCHEMA["schema"]["properties"]["ingredient_sections"][
        "items"
    ]["properties"]["ingredients"]["items"]["required"]

    recipe = Recipe(
        id=uuid4(),
        title="Pasta",
        ingredients=[
            Ingredient(name="flour", quantity="0.5", unit="cup", density_g_per_ml=0.53)
        ],
        ingredient_sections=[
            IngredientSection(
                title="Dough",
                ingredients=[
                    Ingredient(name="flour", quantity="0.5", unit="cup", density_g_per_ml=0.53)
                ],
            )
        ],
        steps=[Step(order=1, text="Mix", duration_minutes=None)],
        source_url="https://example.com/r",
        platform=Platform.youtube,
        tips=[RecipeTip(text="Rest dough")],
    )
    payload = recipe_translation_payload(recipe)
    assert payload["ingredient_sections"][0]["ingredients"][0]["density_g_per_ml"] == 0.53
    # Fingerprint changes when density is added (invalidates stale translations).
    bare = {
        "title": "Pasta",
        "description": None,
        "ingredient_sections": [
            {"title": "Dough", "ingredients": [{"name": "flour", "quantity": "0.5", "unit": "cup"}]}
        ],
        "steps": [{"order": 1, "text": "Mix", "duration_minutes": None}],
        "tags": [],
        "missing_fields": [],
        "tips": [{"title": None, "text": "Rest dough"}],
    }
    with_density = dict(bare)
    with_density["ingredient_sections"] = [
        {
            "title": "Dough",
            "ingredients": [
                {"name": "flour", "quantity": "0.5", "unit": "cup", "density_g_per_ml": 0.53}
            ],
        }
    ]
    assert translation_fingerprint(bare) != translation_fingerprint(with_density)


def test_flat_ingredients_match_section_densities():
    sections = _usable_ingredient_sections(
        [
            {
                "title": "Ingredients",
                "ingredients": [
                    {"name": "salt", "quantity": "0.5", "unit": "cup"},
                    {"name": "all-purpose flour", "quantity": "0.5", "unit": "cup"},
                ],
            }
        ],
        language_code="en-US",
    )
    flat = [item for section in sections for item in section.ingredients]
    assert [item.density_g_per_ml for item in flat] == [
        section.ingredients[i].density_g_per_ml
        for section in sections
        for i in range(len(section.ingredients))
    ]
