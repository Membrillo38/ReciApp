from uuid import uuid4

from app.localization import build_recipe_prompt
from app.models import Ingredient, IngredientSection, Platform, Recipe, RecipeTip, Step
from app.recipe_builder import RECIPE_SCHEMA
from app.store import recipe_public_from_row, recipe_to_row


def test_legacy_recipe_row_gets_single_ingredient_section():
    recipe = recipe_public_from_row(
        {
            "id": str(uuid4()),
            "title": "Legacy recipe",
            "ingredients": [{"name": "flour", "quantity": "200", "unit": "g"}],
            "steps": [],
            "platform": "tiktok",
            "source_url_raw": "https://www.tiktok.com/@cook/video/1",
        }
    )

    assert [section.title for section in recipe.ingredient_sections] == ["Ingredients"]
    assert recipe.ingredient_sections[0].ingredients == recipe.ingredients
    assert recipe.tips == []


def test_structured_recipe_preserves_component_sections_and_tips():
    recipe = recipe_public_from_row(
        {
            "id": str(uuid4()),
            "title": "Chicken wraps",
            "ingredients": [],
            "ingredient_sections": [
                {
                    "title": "Parmesan Chicken",
                    "ingredients": [{"name": "chicken", "quantity": "600", "unit": "g"}],
                },
                {
                    "title": "Creamy Sauce",
                    "ingredients": [{"name": "cream", "quantity": "100", "unit": "g"}],
                },
            ],
            "tips": [{"title": "Storage", "text": "Keep sauce separate."}],
            "steps": [],
            "platform": "tiktok",
            "source_url_raw": "https://www.tiktok.com/@cook/video/1",
        }
    )

    assert [section.title for section in recipe.ingredient_sections] == [
        "Parmesan Chicken",
        "Creamy Sauce",
    ]
    assert [ingredient.name for ingredient in recipe.ingredients] == ["chicken", "cream"]
    assert recipe.tips[0].title == "Storage"


def test_recipe_row_writes_sections_and_tips():
    recipe = Recipe(
        title="Chicken wraps",
        ingredients=[Ingredient(name="chicken", quantity="600", unit="g")],
        ingredient_sections=[
            IngredientSection(
                title="Parmesan Chicken",
                ingredients=[Ingredient(name="chicken", quantity="600", unit="g")],
            )
        ],
        steps=[Step(order=1, text="Cook chicken")],
        source_url="https://www.tiktok.com/@cook/video/1",
        platform=Platform.tiktok,
        tips=[RecipeTip(title="Storage", text="Keep sauce separate.")],
    )

    row = recipe_to_row(recipe, source_url_norm="https://www.tiktok.com/@cook/video/1")

    assert row["ingredient_sections"][0]["title"] == "Parmesan Chicken"
    assert row["tips"][0]["text"] == "Keep sauce separate."


def test_recipe_prompt_and_schema_require_sections_and_tips():
    prompt = build_recipe_prompt("English (US)", "{}")
    properties = RECIPE_SCHEMA["schema"]["properties"]

    assert "Group ingredients into the distinct components" in prompt
    assert "Extract separate actionable tips" in prompt
    assert "slide_text is on-screen overlay OCR" in prompt
    assert "transcript is spoken audio or captions" in prompt
    assert "empty ingredient_sections, empty steps, confidence 0" in prompt
    assert "is_complete" in RECIPE_SCHEMA["schema"]["properties"]
    assert "blocking_gaps" in RECIPE_SCHEMA["schema"]["properties"]
    assert "ingredient_sections" in properties
    assert "tips" in properties


def test_section_flatten_preserves_order_and_intentional_duplicate_names():
    recipe = recipe_public_from_row(
        {
            "id": str(uuid4()),
            "title": "Layered cake",
            "ingredient_sections": [
                {
                    "title": "Cake",
                    "ingredients": [
                        {"name": "sugar", "quantity": "100", "unit": "g"},
                        {"name": "flour", "quantity": "200", "unit": "g"},
                    ],
                },
                {
                    "title": "Frosting",
                    "ingredients": [
                        {"name": "sugar", "quantity": "50", "unit": "g"},
                        {"name": "cream", "quantity": "100", "unit": "ml"},
                    ],
                },
            ],
            "steps": [],
            "platform": "tiktok",
            "source_url_raw": "https://www.tiktok.com/@cook/video/2",
        }
    )

    assert [section.title for section in recipe.ingredient_sections] == ["Cake", "Frosting"]
    assert [(item.name, item.quantity) for item in recipe.ingredients] == [
        ("sugar", "100"),
        ("flour", "200"),
        ("sugar", "50"),
        ("cream", "100"),
    ]
