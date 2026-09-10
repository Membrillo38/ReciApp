from __future__ import annotations

# App Store Connect / Xcode-style identifiers from ReciApp localization spec (exactly 50).
SUPPORTED_LANGUAGE_CODES: tuple[str, ...] = (
    "ar",
    "bn",
    "ca",
    "zh-Hans",
    "zh-Hant",
    "hr",
    "cs",
    "da",
    "nl",
    "en-AU",
    "en-CA",
    "en-GB",
    "en-US",
    "fi",
    "fr-FR",
    "fr-CA",
    "de",
    "el",
    "gu",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "kn",
    "ko",
    "ms",
    "ml",
    "mr",
    "nb",
    "or",
    "pl",
    "pt-BR",
    "pt-PT",
    "pa",
    "ro",
    "ru",
    "sk",
    "sl",
    "es-MX",
    "es-ES",
    "sv",
    "ta",
    "te",
    "th",
    "tr",
    "uk",
    "ur",
    "vi",
)

# English labels for AI prompts (not UI copy).
LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "bn": "Bengali",
    "ca": "Catalan",
    "zh-Hans": "Simplified Chinese",
    "zh-Hant": "Traditional Chinese",
    "hr": "Croatian",
    "cs": "Czech",
    "da": "Danish",
    "nl": "Dutch",
    "en-AU": "English (Australia)",
    "en-CA": "English (Canada)",
    "en-GB": "English (United Kingdom)",
    "en-US": "English",
    "fi": "Finnish",
    "fr-FR": "French",
    "fr-CA": "French (Canada)",
    "de": "German",
    "el": "Greek",
    "gu": "Gujarati",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "kn": "Kannada",
    "ko": "Korean",
    "ms": "Malay",
    "ml": "Malayalam",
    "mr": "Marathi",
    "nb": "Norwegian Bokmål",
    "or": "Odia",
    "pl": "Polish",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "pa": "Punjabi",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "es-MX": "Spanish (Mexico)",
    "es-ES": "Spanish",
    "sv": "Swedish",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
}

UNTITLED_RECIPE_NAMES: dict[str, str] = {
    "ar": "وصفة بدون عنوان",
    "bn": "শিরোনামহীন রেসিপি",
    "ca": "Recepta sense títol",
    "zh-Hans": "未命名食谱",
    "zh-Hant": "未命名食譜",
    "hr": "Recept bez naslova",
    "cs": "Recept bez názvu",
    "da": "Unavngivet opskrift",
    "nl": "Naamloos recept",
    "en-AU": "Untitled recipe",
    "en-CA": "Untitled recipe",
    "en-GB": "Untitled recipe",
    "en-US": "Untitled recipe",
    "fi": "Nimetön resepti",
    "fr-FR": "Recette sans titre",
    "fr-CA": "Recette sans titre",
    "de": "Rezept ohne Titel",
    "el": "Συνταγή χωρίς τίτλο",
    "gu": "શીર્ષક વગરની રેસીપી",
    "he": "מתכון ללא כותרת",
    "hi": "बिना शीर्षक की रेसिपी",
    "hu": "Névtelen recept",
    "id": "Resep tanpa judul",
    "it": "Ricetta senza titolo",
    "ja": "無題のレシピ",
    "kn": "ಶೀರ್ಷಿಕೆಯಿಲ್ಲದ ರೆಸಿಪಿ",
    "ko": "제목 없는 레시피",
    "ms": "Resipi tanpa tajuk",
    "ml": "തലക്കെട്ടില്ലാത്ത പാചകക്കുറിപ്പ്",
    "mr": "शीर्षक नसलेली रेसिपी",
    "nb": "Oppskrift uten tittel",
    "or": "ଶୀର୍ଷକହୀନ ରେସିପି",
    "pl": "Przepis bez tytułu",
    "pt-BR": "Receita sem título",
    "pt-PT": "Receita sem título",
    "pa": "ਬਿਨਾਂ ਸਿਰਲੇਖ ਦੀ ਰੈਸਿਪੀ",
    "ro": "Rețetă fără titlu",
    "ru": "Рецепт без названия",
    "sk": "Recept bez názvu",
    "sl": "Recept brez naslova",
    "es-MX": "Receta sin título",
    "es-ES": "Receta sin título",
    "sv": "Namnlöst recept",
    "ta": "தலைப்பில்லாத செய்முறை",
    "te": "శీర్షిక లేని రెసిపీ",
    "th": "สูตรไม่มีชื่อ",
    "tr": "Başlıksız tarif",
    "uk": "Рецепт без назви",
    "ur": "بلا عنوان ترکیب",
    "vi": "Công thức không tên",
}

INGREDIENT_SECTION_NAMES: dict[str, str] = {
    "ar": "المكونات",
    "bn": "উপকরণ",
    "ca": "Ingredients",
    "zh-Hans": "食材",
    "zh-Hant": "食材",
    "hr": "Sastojci",
    "cs": "Ingredience",
    "da": "Ingredienser",
    "nl": "Ingrediënten",
    "en-AU": "Ingredients",
    "en-CA": "Ingredients",
    "en-GB": "Ingredients",
    "en-US": "Ingredients",
    "fi": "Ainekset",
    "fr-FR": "Ingrédients",
    "fr-CA": "Ingrédients",
    "de": "Zutaten",
    "el": "Υλικά",
    "gu": "ઘટકો",
    "he": "מרכיבים",
    "hi": "सामग्री",
    "hu": "Hozzávalók",
    "id": "Bahan",
    "it": "Ingredienti",
    "ja": "材料",
    "kn": "ಪದಾರ್ಥಗಳು",
    "ko": "재료",
    "ms": "Bahan-bahan",
    "ml": "ചേരുവകൾ",
    "mr": "साहित्य",
    "nb": "Ingredienser",
    "or": "ଉପାଦାନ",
    "pl": "Składniki",
    "pt-BR": "Ingredientes",
    "pt-PT": "Ingredientes",
    "pa": "ਸਮੱਗਰੀ",
    "ro": "Ingrediente",
    "ru": "Ингредиенты",
    "sk": "Ingrediencie",
    "sl": "Sestavine",
    "es-MX": "Ingredientes",
    "es-ES": "Ingredientes",
    "sv": "Ingredienser",
    "ta": "பொருட்கள்",
    "te": "పదార్థాలు",
    "th": "ส่วนผสม",
    "tr": "Malzemeler",
    "uk": "Інгредієнти",
    "ur": "اجزاء",
    "vi": "Nguyên liệu",
}

OPTIONAL_SECTION_NAMES: dict[str, str] = {
    "ar": "اختياري",
    "bn": "ঐচ্ছিক",
    "ca": "Opcional",
    "zh-Hans": "可选",
    "zh-Hant": "可選",
    "hr": "Neobavezno",
    "cs": "Volitelné",
    "da": "Valgfrit",
    "nl": "Optioneel",
    "en-AU": "Optional",
    "en-CA": "Optional",
    "en-GB": "Optional",
    "en-US": "Optional",
    "fi": "Valinnainen",
    "fr-FR": "Optionnel",
    "fr-CA": "Facultatif",
    "de": "Optional",
    "el": "Προαιρετικό",
    "gu": "વૈકલ્પિક",
    "he": "אופציונלי",
    "hi": "वैकल्पिक",
    "hu": "Opcionális",
    "id": "Opsional",
    "it": "Opzionale",
    "ja": "任意",
    "kn": "ಐಚ್ಛಿಕ",
    "ko": "선택",
    "ms": "Pilihan",
    "ml": "ഓപ്ഷണൽ",
    "mr": "पर्यायी",
    "nb": "Valgfritt",
    "or": "ବୈକଳ୍ପିକ",
    "pl": "Opcjonalne",
    "pt-BR": "Opcional",
    "pt-PT": "Opcional",
    "pa": "ਵਿਕਲਪਿਕ",
    "ro": "Opțional",
    "ru": "По желанию",
    "sk": "Voliteľné",
    "sl": "Neobvezno",
    "es-MX": "Opcional",
    "es-ES": "Opcional",
    "sv": "Valfritt",
    "ta": "விருப்பத்தேர்வு",
    "te": "ఐచ్ఛికం",
    "th": "ไม่บังคับ",
    "tr": "İsteğe bağlı",
    "uk": "За бажанням",
    "ur": "اختیاری",
    "vi": "Tùy chọn",
}

# Device / App Store Connect aliases → canonical allowlist code.
_LANGUAGE_ALIASES: dict[str, str] = {
    "ar-sa": "ar",
    "bn-bd": "bn",
    "bn-in": "bn",
    "zh-cn": "zh-Hans",
    "zh-sg": "zh-Hans",
    "zh-tw": "zh-Hant",
    "zh-hk": "zh-Hant",
    "zh-hans-cn": "zh-Hans",
    "zh-hant-tw": "zh-Hant",
    "zh-hant-hk": "zh-Hant",
    "nl-nl": "nl",
    "nl-be": "nl",
    "de-de": "de",
    "de-at": "de",
    "de-ch": "de",
    "gu-in": "gu",
    "he-il": "he",
    "iw": "he",
    "iw-il": "he",
    "kn-in": "kn",
    "ml-in": "ml",
    "mr-in": "mr",
    "nb-no": "nb",
    "nn": "nb",
    "nn-no": "nb",
    "no": "nb",
    "no-no": "nb",
    "or-in": "or",
    "od": "or",
    "pa-in": "pa",
    "pa-pk": "pa",
    "sl-si": "sl",
    "ta-in": "ta",
    "te-in": "te",
    "ur-pk": "ur",
    "ur-in": "ur",
    "es-419": "es-MX",
    "es-us": "es-MX",
    "fr-fr": "fr-FR",
    "en-us": "en-US",
    "en-gb": "en-GB",
    "en-au": "en-AU",
    "en-ca": "en-CA",
    "pt-br": "pt-BR",
    "pt-pt": "pt-PT",
    "es-es": "es-ES",
    "es-mx": "es-MX",
    "fr-ca": "fr-CA",
}

_BASE_LANGUAGE_FALLBACK: dict[str, str] = {
    "ar": "ar",
    "bn": "bn",
    "ca": "ca",
    "zh": "zh-Hans",
    "hr": "hr",
    "cs": "cs",
    "da": "da",
    "nl": "nl",
    "en": "en-US",
    "fi": "fi",
    "fr": "fr-FR",
    "de": "de",
    "el": "el",
    "gu": "gu",
    "he": "he",
    "hi": "hi",
    "hu": "hu",
    "id": "id",
    "it": "it",
    "ja": "ja",
    "kn": "kn",
    "ko": "ko",
    "ms": "ms",
    "ml": "ml",
    "mr": "mr",
    "nb": "nb",
    "or": "or",
    "pl": "pl",
    "pt": "pt-BR",
    "pa": "pa",
    "ro": "ro",
    "ru": "ru",
    "sk": "sk",
    "sl": "sl",
    "es": "es-ES",
    "sv": "sv",
    "ta": "ta",
    "te": "te",
    "th": "th",
    "tr": "tr",
    "uk": "uk",
    "ur": "ur",
    "vi": "vi",
}

_SUPPORTED_LOWER: dict[str, str] = {code.lower(): code for code in SUPPORTED_LANGUAGE_CODES}


def normalize_language(value: str | None) -> str:
    """Return one canonical allowlisted locale."""
    raw = (value or "").strip().replace("_", "-")
    if not raw:
        return "en-US"
    if raw in SUPPORTED_LANGUAGE_CODES:
        return raw

    lowered = raw.lower()
    if lowered in _SUPPORTED_LOWER:
        return _SUPPORTED_LOWER[lowered]
    if lowered in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[lowered]

    # Progressive strip: zh-Hant-TW → zh-Hant → zh
    parts = lowered.split("-")
    for length in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:length])
        if candidate in _SUPPORTED_LOWER:
            return _SUPPORTED_LOWER[candidate]
        if candidate in _LANGUAGE_ALIASES:
            return _LANGUAGE_ALIASES[candidate]

    base = parts[0]
    return _BASE_LANGUAGE_FALLBACK.get(base, "en-US")


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
        "If a hands-on action is followed by waiting (fridge, freezer, rest, marinate, soak), "
        "emit TWO steps: the action with duration_minutes null, then a short wait-only step "
        "with duration_minutes set. Never glue shaping, mixing, or plating into the wait step.\n"
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
        "Missing servings, prep_minutes, cook_minutes, or temperatures alone do NOT make the recipe "
        "incomplete and must NOT appear in blocking_gaps. "
        "List every blocking gap in blocking_gaps when is_complete is false.\n"
        "If the source does not contain a real cooking recipe with ingredients and a method, return "
        "empty ingredient_sections, empty steps, confidence 0, is_complete false, and blocking_gaps "
        "explaining why. Do not invent a recipe from a title, marketing caption, or hashtags.\n\n"
        f"SOURCE:\n{source_json}"
    )
