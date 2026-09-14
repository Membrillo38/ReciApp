from app.job_errors import (
    EXTRACTION_RETRYABLE,
    RECIPE_INCOMPLETE,
    RECIPE_NO_INGREDIENTS,
    RECIPE_NO_METHOD,
    RECIPE_UNDETERMINED,
    VIDEO_TOO_LONG,
    canonicalize_job_error,
    job_error_code,
    localize_job_error,
)
from app.localization import SUPPORTED_LANGUAGE_CODES


def test_canonicalize_maps_legacy_and_dynamic_errors():
    assert canonicalize_job_error("Video too long (400s). Max 180s.") == VIDEO_TOO_LONG
    assert canonicalize_job_error("Incomplete TikTok carousel: missing slides") == (
        "This TikTok carousel is incomplete. Try another link or a full recipe video."
    )
    assert canonicalize_job_error("totally unknown provider boom") == EXTRACTION_RETRYABLE
    assert job_error_code(RECIPE_NO_INGREDIENTS) == "recipe_no_ingredients"


def test_localize_job_error_covers_all_locales_and_types():
    messages = [
        RECIPE_UNDETERMINED,
        RECIPE_INCOMPLETE,
        RECIPE_NO_INGREDIENTS,
        RECIPE_NO_METHOD,
    ]
    for message in messages:
        for code in SUPPORTED_LANGUAGE_CODES:
            localized = localize_job_error(message, code)
            assert localized
            assert localized.strip()
    assert localize_job_error(RECIPE_NO_INGREDIENTS, "es-ES") == (
        "Este vídeo no incluye una lista clara de ingredientes."
    )
    assert localize_job_error(RECIPE_NO_METHOD, "es-ES") == (
        "Este vídeo no incluye pasos de cocción claros."
    )
    assert localize_job_error(RECIPE_INCOMPLETE, "de") == (
        "Aus diesem Video konnte kein vollständiges Rezept extrahiert werden."
    )
    assert localize_job_error(RECIPE_UNDETERMINED, "en-US") == RECIPE_UNDETERMINED
