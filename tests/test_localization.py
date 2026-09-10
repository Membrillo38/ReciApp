import pytest
import json
import re
from collections import Counter
from pathlib import Path

from app.localization import (
    INGREDIENT_SECTION_NAMES,
    LANGUAGE_NAMES,
    SUPPORTED_LANGUAGE_CODES,
    UNTITLED_RECIPE_NAMES,
    ingredient_section_name,
    language_name,
    normalize_language,
    untitled_recipe_name,
)
from app.models import ExtractRequest
from app.localization import build_recipe_prompt


def test_allowlist_has_six_canonical_latin_locales():
    expected = {"en-US", "es-ES", "fr-FR", "de", "it", "pt-BR"}
    assert len(SUPPORTED_LANGUAGE_CODES) == 6
    assert len(set(SUPPORTED_LANGUAGE_CODES)) == 6
    assert set(SUPPORTED_LANGUAGE_CODES) == expected
    assert set(LANGUAGE_NAMES) == expected


def test_language_normalization_handles_regions_and_unknown_values():
    assert normalize_language("es-ES") == "es-ES"
    assert normalize_language("pt_br") == "pt-BR"
    assert normalize_language("pt-PT") == "pt-BR"
    assert normalize_language("zh-Hant-TW") == "en-US"
    assert normalize_language("en") == "en-US"
    assert normalize_language("not-a-language") == "en-US"
    assert language_name("es") == "Spanish"


def test_extract_request_carries_language():
    request = ExtractRequest(url="https://youtube.com/watch?v=abc", language="ja")
    assert request.language == "ja"


def test_recipe_prompt_requires_target_language():
    prompt = build_recipe_prompt("German", "{}")
    assert "in German" in prompt
    assert "title, description, ingredient names" in prompt


def test_fallback_recipe_copy_is_localized():
    assert untitled_recipe_name("ja") == "Untitled recipe"
    assert ingredient_section_name("fr-FR") == "Ingrédients"
    assert set(SUPPORTED_LANGUAGE_CODES) == set(UNTITLED_RECIPE_NAMES)
    assert set(SUPPORTED_LANGUAGE_CODES) == set(INGREDIENT_SECTION_NAMES)


@pytest.mark.skipif(not Path("IosAPP/ReciApp").is_dir(), reason="Ignored iOS sources unavailable in backend-only checkout")
def test_ios_catalog_covers_all_supported_locales_and_placeholders():
    catalog_path = Path(__file__).parents[1] / "IosAPP" / "ReciApp" / "Localizable.xcstrings"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog["strings"]) == 229

    token_pattern = re.compile(r"%(?:\d+\$)?(?:lld|d|@|%)")

    for key, entry in catalog["strings"].items():
        source_tokens = [re.sub(r"%(?:\d+\$)?", "%", token) for token in token_pattern.findall(key)]
        localizations = entry.get("localizations", {})
        assert set(localizations) == set(SUPPORTED_LANGUAGE_CODES), key
        for locale in SUPPORTED_LANGUAGE_CODES:
            value = localizations[locale]["stringUnit"]["value"]
            localized_tokens = [re.sub(r"%(?:\d+\$)?", "%", token) for token in token_pattern.findall(value)]
            assert Counter(localized_tokens) == Counter(source_tokens), (locale, key, value)


@pytest.mark.skipif(not Path("IosAPP/ReciApp").is_dir(), reason="Ignored iOS sources unavailable in backend-only checkout")
def test_ios_folder_move_supports_multiple_selection():
    root = Path(__file__).parents[1]
    home = (root / "IosAPP" / "ReciApp" / "Views" / "HomeView.swift").read_text(encoding="utf-8")
    catalog = json.loads((root / "IosAPP" / "ReciApp" / "Localizable.xcstrings").read_text(encoding="utf-8"))
    assert "moveRecipes(withIDs:" in home
    assert "selectedIDs" in home
    assert "FolderSelectionBar" in home
    assert "Select" in catalog["strings"]
    assert "Select All" in catalog["strings"]


@pytest.mark.skipif(not Path("IosAPP/ReciApp").is_dir(), reason="Ignored iOS sources unavailable in backend-only checkout")
def test_share_extension_uses_shared_localization_resources():
    root = Path(__file__).parents[1]
    share_controller = (root / "IosAPP" / "ReciAppShare" / "ShareViewController.swift").read_text(encoding="utf-8")
    project = (root / "IosAPP" / "ReciApp.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
    localization = (root / "IosAPP" / "ReciApp" / "Services" / "Localization.swift").read_text(encoding="utf-8")
    app_model = (root / "IosAPP" / "ReciApp" / "ViewModels" / "AppViewModel.swift").read_text(encoding="utf-8")
    app_entitlements = (root / "IosAPP" / "ReciApp" / "ReciApp.entitlements").read_text(encoding="utf-8")
    share_entitlements = (root / "IosAPP" / "ReciAppShare" / "ReciAppShare.entitlements").read_text(encoding="utf-8")
    assert "ReciLocalization.string(\"Opening ReciApp…\")" in share_controller
    assert "No se encontró un enlace compatible" not in share_controller
    assert "Localizable.xcstrings in Resources" in project
    assert "Localization.swift" in project
    assert project.count("Localizable.xcstrings in Resources") >= 2
    assert 'appGroupIdentifier = "group.com.membri.reciapp"' in localization
    assert "group.com.membri.reciapp" in app_entitlements
    assert "group.com.membri.reciapp" in share_entitlements
    assert "localizedCategoryName" in app_model
    app_entry = (root / "IosAPP" / "ReciApp" / "ReciAppApp.swift").read_text(encoding="utf-8")
    assert "-reciapp-settings-preview" in app_entry
    recipe_detail = (root / "IosAPP" / "ReciApp" / "Views" / "RecipeDetailView.swift").read_text(encoding="utf-8")
    assert "AppLanguageStore.current.localeIdentifier" in recipe_detail
    models = (root / "IosAPP" / "ReciApp" / "Models" / "Models.swift").read_text(encoding="utf-8")
    assert "localizedServerMessage" in models
    profile = (root / "IosAPP" / "ReciApp" / "Views" / "ProfileView.swift").read_text(encoding="utf-8")
    assert "AppLanguageStore.selection = newValue" in profile
