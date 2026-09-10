from app.models import Ingredient, IngredientSection
from app.recipe_builder import power_up_ingredient_sections


def test_power_up_splits_optional_heading_and_inline_markers():
    sections = [
        IngredientSection(
            title="Ingredientes",
            ingredients=[
                Ingredient(name="harina", quantity="200", unit="g"),
                Ingredient(name="agua", quantity="100", unit="ml"),
                Ingredient(name="Opcional:"),
                Ingredient(name="queso", quantity="50", unit="g"),
                Ingredient(name="perejil (opcional)"),
            ],
        )
    ]

    powered = power_up_ingredient_sections(sections, language_code="es-ES")

    assert [section.title for section in powered] == ["Ingredientes", "Opcional"]
    assert [ing.name for ing in powered[0].ingredients] == ["harina", "agua"]
    assert [ing.name for ing in powered[1].ingredients] == ["queso", "perejil"]


def test_power_up_splits_for_the_sauce_heading():
    sections = [
        IngredientSection(
            title="Ingredients",
            ingredients=[
                Ingredient(name="chicken", quantity="600", unit="g"),
                Ingredient(name="For the sauce"),
                Ingredient(name="cream", quantity="100", unit="ml"),
                Ingredient(name="garlic", quantity="2", unit="cloves"),
            ],
        )
    ]

    powered = power_up_ingredient_sections(sections, language_code="en-US")

    assert [section.title for section in powered] == ["Ingredients", "For the sauce"]
    assert [ing.name for ing in powered[1].ingredients] == ["cream", "garlic"]


def test_power_up_keeps_component_sections():
    sections = [
        IngredientSection(
            title="Dough",
            ingredients=[Ingredient(name="flour", quantity="200", unit="g")],
        ),
        IngredientSection(
            title="Optional",
            ingredients=[Ingredient(name="sesame seeds", quantity="1", unit="tbsp")],
        ),
    ]

    powered = power_up_ingredient_sections(sections, language_code="en-US")

    assert [section.title for section in powered] == ["Dough", "Optional"]
    assert powered[1].ingredients[0].name == "sesame seeds"
