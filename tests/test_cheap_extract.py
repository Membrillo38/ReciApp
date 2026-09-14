"""Cheap extract path: skip paid STT/OCR when cheaper stages already work."""

from __future__ import annotations

from uuid import uuid4

import pytest

import app.extract as extract
from app.config import settings
from app.models import Ingredient, IngredientSection, Platform, Recipe, Step
from app.tiktok_slides import SlideInfo


def _complete_recipe(**kwargs) -> Recipe:
    ingredient = Ingredient(name="egg")
    return Recipe(
        title="Eggs",
        ingredients=[ingredient],
        ingredient_sections=[IngredientSection(title="Ingredients", ingredients=[ingredient])],
        steps=[Step(order=1, text="Cook egg")],
        confidence=0.9,
        source_url=kwargs.get("source_url") or "https://example.com",
        platform=Platform.tiktok,
    )


def test_default_margin_is_forty_percent(monkeypatch):
    from app.limits import AppDefaults, resolve_user_limits

    assert AppDefaults().pro_margin_ratio == 0.40
    monkeypatch.setattr(
        "app.limits.get_app_defaults",
        lambda: AppDefaults(pro_margin_ratio=0.40),
    )
    limits = resolve_user_limits(
        {
            "free_weekly_limit": 10,
            "pro_monthly_price_cents": 1000,
            "pro_margin_ratio": None,
        }
    )
    assert limits.pro_margin_ratio == 0.40
    assert limits.pro_budget_cents == 600.0


def test_max_job_cost_default_is_fifty_cents():
    assert settings.max_job_cost_cents == 50.0
    assert settings.max_vision_frames == 12


def test_carousel_caption_complete_skips_ocr(monkeypatch):
    import app.pipeline as pipeline

    slides = SlideInfo(
        title="Full pasta recipe",
        description="Ingredients: pasta, salt. Steps: boil water, cook pasta, serve.",
        author="cook",
        image_urls=["https://cdn.example/1.jpg", "https://cdn.example/2.jpg"],
        total_image_count=2,
    )
    ocr_calls = []
    settled = []
    recipe_id = uuid4()

    monkeypatch.setattr(pipeline, "detect_platform", lambda url: Platform.tiktok)
    monkeypatch.setattr(pipeline, "fetch_tiktok_slides", lambda url: slides)
    monkeypatch.setattr(
        pipeline,
        "ocr_one_slide",
        lambda **kwargs: ocr_calls.append(kwargs) or pytest.fail("OCR must not run"),
    )
    monkeypatch.setattr(pipeline, "build_recipe", lambda **kwargs: _complete_recipe(**kwargs))
    monkeypatch.setattr(pipeline, "update_job", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "upsert_recipe", lambda *a, **k: {"id": str(recipe_id)})
    monkeypatch.setattr(pipeline, "save_user_recipe", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "record_usage", lambda **k: None)
    monkeypatch.setattr(pipeline, "settle_spend", lambda **k: settled.append(k))
    monkeypatch.setattr(pipeline, "release_job", lambda *a: None)
    monkeypatch.setattr(pipeline, "_drain_next_extract_for_user", lambda *a, **k: None)

    pipeline.run_extract_job(
        uuid4(),
        uuid4(),
        "https://www.tiktok.com/@cook/photo/1",
        "tiktok:photo:1",
        "en-US",
    )

    assert ocr_calls == []
    assert settled[-1]["actual_cents"] == 0


def test_carousel_link_in_bio_skips_ocr(monkeypatch):
    import app.pipeline as pipeline

    slides = SlideInfo(
        title="Yummy",
        description="Full recipe in bio!",
        author="cook",
        image_urls=["https://cdn.example/1.jpg"],
        total_image_count=1,
    )
    jobs = []
    ocr_calls = []
    settled = []

    monkeypatch.setattr(pipeline, "detect_platform", lambda url: Platform.tiktok)
    monkeypatch.setattr(pipeline, "fetch_tiktok_slides", lambda url: slides)
    monkeypatch.setattr(
        pipeline,
        "ocr_one_slide",
        lambda **kwargs: ocr_calls.append(kwargs) or "should not run",
    )
    monkeypatch.setattr(pipeline, "update_job", lambda *a, **k: jobs.append(k))
    monkeypatch.setattr(pipeline, "settle_spend", lambda **k: settled.append(k))
    monkeypatch.setattr(pipeline, "release_job", lambda *a: None)
    monkeypatch.setattr(pipeline, "_drain_next_extract_for_user", lambda *a, **k: None)

    pipeline.run_extract_job(
        uuid4(),
        uuid4(),
        "https://www.tiktok.com/@cook/photo/1",
        "tiktok:photo:bio",
        "en-US",
    )

    assert ocr_calls == []
    assert jobs[-1]["status"] == "failed"
    assert settled[-1]["actual_cents"] == 0


def test_openai_stt_skipped_when_local_transcript_is_rich(monkeypatch, tmp_path):
    import app.pipeline as pipeline

    audio = tmp_path / "a.wav"
    audio.write_bytes(b"fake")
    media = extract.MediaInfo(
        title="Dinner",
        description="Short",
        author="cook",
        thumbnail_url=None,
        duration_seconds=40,
        webpage_url="https://www.tiktok.com/@cook/video/9",
        subtitles_text=None,
        audio_path=None,
        media_id="9",
    )
    stt_calls = []
    settled = []
    recipe_id = uuid4()
    local_text = "A" * (settings.local_stt_min_chars + 5)

    def fake_build(**kwargs):
        if kwargs.get("transcript") and local_text in (kwargs.get("transcript") or ""):
            return _complete_recipe(**kwargs)
        return None

    monkeypatch.setattr(pipeline, "detect_platform", lambda url: Platform.tiktok)
    monkeypatch.setattr(pipeline, "fetch_tiktok_slides", lambda url: None)
    monkeypatch.setattr(pipeline, "fetch_media_info", lambda url: media)
    monkeypatch.setattr(pipeline, "download_audio", lambda *a, **k: audio)
    monkeypatch.setattr(pipeline, "local_transcript", lambda *a, **k: local_text)
    monkeypatch.setattr(
        pipeline,
        "whisper_transcript",
        lambda *a, **k: stt_calls.append(1) or "paid",
    )
    monkeypatch.setattr(
        pipeline,
        "download_video_frames",
        lambda *a, **k: pytest.fail("vision must not run"),
    )
    monkeypatch.setattr(pipeline, "build_recipe", fake_build)
    monkeypatch.setattr(pipeline, "choose_video_cover_url", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "update_job", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "upsert_recipe", lambda *a, **k: {"id": str(recipe_id)})
    monkeypatch.setattr(pipeline, "save_user_recipe", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "record_usage", lambda **k: None)
    monkeypatch.setattr(pipeline, "settle_spend", lambda **k: settled.append(k))
    monkeypatch.setattr(pipeline, "release_job", lambda *a: None)
    monkeypatch.setattr(pipeline, "_drain_next_extract_for_user", lambda *a, **k: None)

    pipeline.run_extract_job(uuid4(), uuid4(), media.webpage_url, "tiktok:9", "en-US")

    assert stt_calls == []
    assert settled[-1]["status"] == "settled"


def test_recipe_model_stops_after_rate_limit(monkeypatch):
    import app.recipe_builder as recipe_builder

    calls = []

    class RateLimitError(Exception):
        pass

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs.get("max_tokens"))
            raise RateLimitError("slow down")

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = type("C", (), {"completions": FakeCompletions()})()

    monkeypatch.setattr(recipe_builder, "OpenAI", FakeClient)
    monkeypatch.setattr(recipe_builder.settings, "openai_api_key", "test")

    with pytest.raises(extract.ExtractError, match="temporarily unavailable"):
        recipe_builder._request_structured_recipe(
            [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        )

    assert calls == [2400]
