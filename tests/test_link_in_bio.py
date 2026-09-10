from app.recipe_builder import LINK_IN_BIO_ERROR, reject_link_in_bio, text_points_to_link_in_bio
from app.extract import ExtractError
from app.pipeline import _safe_job_error


def test_link_in_bio_phrases():
    assert text_points_to_link_in_bio("Full recipe link in bio 🍝")
    assert text_points_to_link_in_bio("Receta completa en la bio")
    assert text_points_to_link_in_bio("mira mi bio para la receta")
    assert text_points_to_link_in_bio("check my bio")
    assert text_points_to_link_in_bio("link en la biografía")
    assert not text_points_to_link_in_bio("Homemade carbonara recipe")
    assert not text_points_to_link_in_bio("biology class notes")


def test_reject_raises_stable_error():
    try:
        reject_link_in_bio("recipe in bio")
        raise AssertionError("expected ExtractError")
    except ExtractError as exc:
        assert str(exc) == LINK_IN_BIO_ERROR
        assert _safe_job_error(exc) == LINK_IN_BIO_ERROR
