import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import app.recipe_builder as recipe_builder
import app.extract as extract
from app.costing import estimate_miss_cost_cents
from app.config import settings
from app.pipeline import _safe_job_error
from app.models import Platform
from app.tiktok_slides import (
    MAX_CAROUSEL_SLIDES,
    SlideInfo,
    _dig_item_struct,
    _image_urls,
    _slide_info_from_html,
    _photo_meta_fallback,
    fetch_tiktok_slides,
)


def test_tiktok_urls_are_bounded_deduplicated_and_use_largest_variant():
    images = [
        {"imageURL": {"urlList": ["https://cdn.example/1-small.jpg", "https://cdn.example/1-large.jpg"]}},
        {"imageURL": {"urlList": ["https://cdn.example/1-large.jpg", "https://cdn.example/2-large.jpg"]}},
    ]
    assert _image_urls(images) == [
        "https://cdn.example/1-large.jpg",
        "https://cdn.example/2-large.jpg",
    ]


def test_tiktok_photo_meta_fallback_preserves_public_image_order():
    html = '''
    <meta property="og:title" content="Pasta carousel">
    <meta property="og:description" content="Boil pasta">
    <meta property="og:image" content="https://cdn.example/slide-1.jpg">
    <meta property="og:image" content="https://cdn.example/slide-2.jpg">
    <meta name="twitter:image" content="https://cdn.example/slide-2.jpg">
    '''
    result = _photo_meta_fallback(
        html,
        "https://www.tiktok.com/@cook/photo/1",
    )
    assert result is not None
    assert result.image_urls == [
        "https://cdn.example/slide-1.jpg",
        "https://cdn.example/slide-2.jpg",
    ]
    assert result.incomplete_reason is not None


def test_tiktok_hydration_fallback_finds_nested_photo_payload():
    result = _dig_item_struct({
        "newRoot": {
            "item": {
                "imagePost": {
                    "images": [{"imageURL": {"urlList": ["https://cdn.example/slide.jpg"]}}]
                }
            }
        }
    })
    assert result and "imagePost" in result


def test_photo_post_retries_mobile_ssr_when_desktop_shell_has_no_images():
    mobile_html = (
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
        + json.dumps({
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "itemStruct": {
                            "desc": "High protein pasta",
                            "author": {"uniqueId": "cook"},
                            "imagePost": {
                                "title": "High protein pasta",
                                "images": [
                                    {"imageURL": {"urlList": [f"https://cdn.example/slide-{i}.jpg"]}}
                                    for i in range(1, 4)
                                ],
                            },
                        }
                    }
                }
            }
        })
        + '</script>'
    )
    original_fetch = __import__("app.tiktok_slides", fromlist=["_fetch_html"])._fetch_html
    import app.tiktok_slides as slides
    calls = []

    def fake_fetch(url, *, user_agent=slides.UA):
        calls.append(user_agent)
        return mobile_html if len(calls) == 2 else "<html>desktop shell</html>"

    slides._fetch_html = fake_fetch
    try:
        result = fetch_tiktok_slides("https://www.tiktok.com/@cook/photo/1")
    finally:
        slides._fetch_html = original_fetch

    assert result is not None
    assert result.image_urls == [
        "https://cdn.example/slide-1.jpg",
        "https://cdn.example/slide-2.jpg",
        "https://cdn.example/slide-3.jpg",
    ]
    assert calls == [slides.MOBILE_UA, slides.UA]


def test_photo_post_retries_mobile_ssr_after_empty_first_fetch():
    import app.tiktok_slides as slides

    mobile_html = (
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
        + json.dumps({
            "__DEFAULT_SCOPE__": {
                "webapp.video-detail": {
                    "itemInfo": {
                        "itemStruct": {
                            "desc": "Photo recipe",
                            "imagePost": {
                                "images": [{"imageURL": {"urlList": ["https://cdn.example/slide.jpg"]}}]
                            },
                        }
                    }
                }
            }
        })
        + '</script>'
    )
    original_fetch = slides._fetch_html
    calls = []

    def fake_fetch(url, *, user_agent=slides.UA):
        calls.append(user_agent)
        return mobile_html if len(calls) == 2 else None

    slides._fetch_html = fake_fetch
    try:
        result = fetch_tiktok_slides("https://www.tiktok.com/@cook/photo/2")
    finally:
        slides._fetch_html = original_fetch

    assert result is not None
    assert result.image_urls == ["https://cdn.example/slide.jpg"]
    assert calls == [slides.MOBILE_UA, slides.UA]


def test_video_url_skips_carousel_probe_and_leaves_media_to_ytdlp():
    import app.tiktok_slides as slides

    original_fetch = slides._fetch_html
    slides._fetch_html = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("video must not probe carousel HTML")
    )
    try:
        result = fetch_tiktok_slides("https://www.tiktok.com/@cook/video/3")
    finally:
        slides._fetch_html = original_fetch

    assert result is None


def test_tiktok_html_retries_one_transient_fetch_failure():
    import app.tiktok_slides as slides

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b"<html>ok</html>"

    calls = []
    original_open = slides.safe_urlopen
    original_validate = slides.validate_public_url

    def fake_open(request, *, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise TimeoutError("temporary")
        return Response()

    slides.safe_urlopen = fake_open
    slides.validate_public_url = lambda *args, **kwargs: None
    try:
        assert slides._fetch_html("https://www.tiktok.com/@cook/photo/1") == "<html>ok</html>"
    finally:
        slides.safe_urlopen = original_open
        slides.validate_public_url = original_validate

    assert len(calls) == 2


def test_tiktok_slide_download_retries_one_transient_fetch_failure():
    import app.tiktok_slides as slides

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, _limit):
            return b"x" * 500

    calls = []
    original_open = slides.safe_urlopen
    original_validate = slides.validate_public_url

    def fake_open(request, *, timeout):
        calls.append((request.full_url, timeout))
        if len(calls) == 1:
            raise TimeoutError("temporary")
        return Response()

    slides.safe_urlopen = fake_open
    slides.validate_public_url = lambda *args, **kwargs: None
    try:
        result = slides.download_image_b64("https://cdn.example/slide.jpg")
    finally:
        slides.safe_urlopen = original_open
        slides.validate_public_url = original_validate

    assert result
    assert len(calls) == 2


def test_ocr_processes_all_bounded_slides_then_rejects_any_unreadable_slide():
    import app.transcript as transcript
    from app.tiktok_slides import MAX_CAROUSEL_SLIDES, SlideInfo

    requested: list[str] = []
    model_calls: list[int] = []

    def fake_download(url):
        requested.append(url)
        if url.endswith("slide-2.jpg"):
            raise RuntimeError("temporary CDN failure")
        return "ZmFrZQ=="

    class FakeCompletions:
        def create(self, **kwargs):
            model_calls.append(kwargs["messages"][0]["content"][0]["text"])
            if len(model_calls) == 3:
                return SimpleNamespace(choices=[])
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ingredient"))]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    original_download = transcript.download_image_b64
    original_client = transcript.OpenAI
    original_key = transcript.settings.openai_api_key
    transcript.download_image_b64 = fake_download
    transcript.OpenAI = FakeClient
    transcript.settings.openai_api_key = "test-key"
    try:
        with pytest.raises(extract.ExtractError, match="unreadable slides 2,4"):
            transcript.ocr_slides(
                SlideInfo(
                    title="Carousel",
                    description="",
                    author=None,
                    image_urls=[f"https://cdn.example/slide-{i}.jpg" for i in range(1, 13)],
                    total_image_count=MAX_CAROUSEL_SLIDES,
                )
            )
    finally:
        transcript.download_image_b64 = original_download
        transcript.OpenAI = original_client
        transcript.settings.openai_api_key = original_key

    assert len(requested) == MAX_CAROUSEL_SLIDES
    assert len(model_calls) == MAX_CAROUSEL_SLIDES - 1
    assert len(model_calls) == MAX_CAROUSEL_SLIDES - 1


def test_hydration_marks_carousel_over_bound_incomplete_without_hiding_count():
    html = (
        '<script id="SIGI_STATE">'
        + json.dumps({
            "ItemModule": {
                "1": {
                    "desc": "Recipe",
                    "imagePost": {
                        "images": [
                            {"imageURL": {"urlList": [f"https://cdn.example/{i}.jpg"]}}
                            for i in range(MAX_CAROUSEL_SLIDES + 1)
                        ]
                    },
                }
            }
        })
        + "</script>"
    )
    result = _slide_info_from_html(html)
    assert result is not None
    assert len(result.image_urls) == MAX_CAROUSEL_SLIDES
    assert result.total_image_count == MAX_CAROUSEL_SLIDES + 1
    assert result.incomplete_reason is not None


def test_hydration_marks_invalid_slide_reference_incomplete():
    html = (
        '<script id="SIGI_STATE">'
        + json.dumps({
            "ItemModule": {
                "1": {
                    "imagePost": {
                        "images": [
                            {"imageURL": {"urlList": ["https://cdn.example/1.jpg"]}},
                            {"imageURL": {"urlList": ["http://private.invalid/2.jpg"]}},
                        ]
                    }
                }
            }
        })
        + "</script>"
    )
    result = _slide_info_from_html(html)
    assert result is not None
    assert result.total_image_count == 2
    assert len(result.image_urls) == 1
    assert result.incomplete_reason is not None


def test_ocr_rejects_truncated_model_output():
    import app.transcript as transcript

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="partial"),
                    finish_reason="length",
                )]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    original_client = transcript.OpenAI
    original_download = transcript.download_image_b64
    original_key = transcript.settings.openai_api_key
    transcript.OpenAI = FakeClient
    transcript.download_image_b64 = lambda url: "ZmFrZQ=="
    transcript.settings.openai_api_key = "test-key"
    try:
        with pytest.raises(extract.ExtractError, match="unreadable slides 1"):
            transcript.ocr_slides(SlideInfo("x", "", None, ["https://cdn.example/1.jpg"], total_image_count=1))
    finally:
        transcript.OpenAI = original_client
        transcript.download_image_b64 = original_download
        transcript.settings.openai_api_key = original_key


def test_carousel_cost_accounts_for_all_bounded_ocr_slides():
    from app.tiktok_slides import MAX_CAROUSEL_SLIDES

    expected = round(
        settings.cost_text_cents_per_extract
        + MAX_CAROUSEL_SLIDES * settings.cost_ocr_cents_per_slide,
        4,
    )
    assert estimate_miss_cost_cents(slide_count=MAX_CAROUSEL_SLIDES) == expected


def test_video_frame_cost_is_bounded_to_three_attempts():
    expected = round(
        settings.cost_text_cents_per_extract + 3 * settings.cost_ocr_cents_per_slide,
        4,
    )
    assert estimate_miss_cost_cents(frame_count=20) == expected
def test_structured_output_retries_malformed_json():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            content = '{"title":"cut' if len(calls) == 1 else '{"title":"ok"}'
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content, refusal=None),
                        finish_reason="stop",
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    original = recipe_builder.OpenAI
    recipe_builder.OpenAI = FakeClient
    try:
        result = recipe_builder._request_structured_recipe(
            [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        )
    finally:
        recipe_builder.OpenAI = original

    assert result["title"] == "ok"
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == 2400
    assert calls[1]["max_tokens"] == 4000


def test_structured_output_retries_transient_provider_error():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise RuntimeError("temporary provider failure")
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"title":"ok"}', refusal=None),
                        finish_reason="stop",
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    original = recipe_builder.OpenAI
    recipe_builder.OpenAI = FakeClient
    try:
        result = recipe_builder._request_structured_recipe(
            [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        )
    finally:
        recipe_builder.OpenAI = original

    assert result["title"] == "ok"
    assert len(calls) == 2


def test_structured_output_retries_empty_model_response():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return SimpleNamespace(choices=[])
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content='{"title":"ok"}', refusal=None),
                        finish_reason="stop",
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    original = recipe_builder.OpenAI
    recipe_builder.OpenAI = FakeClient
    try:
        result = recipe_builder._request_structured_recipe(
            [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]
        )
    finally:
        recipe_builder.OpenAI = original

    assert result["title"] == "ok"
    assert len(calls) == 2


def test_pipeline_logs_stage_without_source_payload_logging():
    source = Path("app/pipeline.py").read_text(encoding="utf-8")
    assert 'extract stage=media' in source
    assert 'extract stage=ocr_video_frame' not in source
    assert 'extract stage=whisper_fallback' in source
    assert 'extract stage=persisted' in source
    assert 'logger.warning("recipe_model attempt=%d error_type=%s"' not in source
    assert 'f"Unexpected error: {exc}"' not in source
    assert "_RETRYABLE_EXTRACTION_ERROR" in source


def test_video_frame_ocr_preserves_order_and_counts_attempts(tmp_path):
    import app.transcript as transcript

    frames = []
    for index in range(1, 4):
        path = tmp_path / f"frame-{index}.jpg"
        path.write_bytes(f"frame-{index}".encode())
        frames.append(path)
    attempts = []

    class FakeCompletions:
        def create(self, **kwargs):
            label = kwargs["messages"][0]["content"][0]["text"].split(".", 1)[0]
            return SimpleNamespace(
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content=label),
                    finish_reason="stop",
                )]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    original_client = transcript.OpenAI
    original_key = transcript.settings.openai_api_key
    transcript.OpenAI = FakeClient
    transcript.settings.openai_api_key = "test-key"
    try:
        result = transcript.ocr_video_frames(frames, on_attempt=lambda: attempts.append(1))
    finally:
        transcript.OpenAI = original_client
        transcript.settings.openai_api_key = original_key

    assert result.split("\n\n") == [
        "Sampled video frame 1",
        "Sampled video frame 2",
        "Sampled video frame 3",
    ]
    assert len(attempts) == 3


def test_video_frame_sampler_bounds_tools_and_removes_download(tmp_path):
    original_ytdlp = extract._run_ytdlp
    original_run = extract.subprocess.run
    original_which = extract.shutil.which
    original_validate = extract.validate_public_url
    calls = []

    def fake_ytdlp(args, timeout):
        output = Path(args[args.index("-o") + 1])
        output.write_bytes(b"v" * 1_000)
        calls.append((args, timeout, output))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def fake_run(command, **kwargs):
        if command[0].endswith("ffprobe"):
            calls.append((command, kwargs))
            return SimpleNamespace(returncode=0, stdout="20.0\n", stderr="")
        frame = Path(command[-1])
        frame.write_bytes(b"j" * 600)
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    extract._run_ytdlp = fake_ytdlp
    extract.subprocess.run = fake_run
    extract.shutil.which = lambda name: f"/usr/local/bin/{name}"
    extract.validate_public_url = lambda *args, **kwargs: None
    try:
        result = extract.download_tiktok_video_frames(
            "https://www.tiktok.com/@cook/video/1",
            media_id="../../unsafe",
            duration_seconds=20,
        )
        assert len(result.paths) == 3
        assert all(path.is_file() for path in result.paths)
        assert not calls[0][2].exists()
        assert calls[0][1] == extract.VIDEO_DOWNLOAD_TIMEOUT_SECONDS
        assert calls[1][1]["timeout"] == extract.VIDEO_PROBE_TIMEOUT_SECONDS
        assert all(call[1]["timeout"] == extract.FRAME_EXTRACT_TIMEOUT_SECONDS for call in calls[2:])
    finally:
        extract._run_ytdlp = original_ytdlp
        extract.subprocess.run = original_run
        extract.shutil.which = original_which
        extract.validate_public_url = original_validate
        if "result" in locals():
            extract.shutil.rmtree(result.directory, ignore_errors=True)


def test_video_frame_sampler_cleans_temporary_media_on_failure():
    original_ytdlp = extract._run_ytdlp
    original_which = extract.shutil.which
    original_validate = extract.validate_public_url
    directory = None

    def fake_ytdlp(args, timeout):
        nonlocal directory
        output = Path(args[args.index("-o") + 1])
        directory = output.parent
        output.write_bytes(b"v" * 1_000)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    extract._run_ytdlp = fake_ytdlp
    extract.shutil.which = lambda name: None
    extract.validate_public_url = lambda *args, **kwargs: None
    try:
        with pytest.raises(extract.ExtractError, match="ffmpeg and ffprobe"):
            extract.download_tiktok_video_frames(
                "https://www.tiktok.com/@cook/video/1",
                media_id="1",
                duration_seconds=20,
            )
    finally:
        extract._run_ytdlp = original_ytdlp
        extract.shutil.which = original_which
        extract.validate_public_url = original_validate

    assert directory is not None and not directory.exists()


def test_bounded_recipe_source_never_slices_ordered_ocr_json():
    final_marker = "FINAL-SLIDE-12"
    payload = {
        "platform": "tiktok",
        "title": "title" * 1_000,
        "description": "description" * 2_000,
        "author": "cook",
        "transcript": "spoken" * 3_000,
        "slide_text": "slide\n" * 2_000 + final_marker,
    }
    encoded = recipe_builder._bounded_source_json(payload)
    decoded = json.loads(encoded)
    assert decoded["slide_text"].endswith(final_marker)
    assert len(encoded) <= 24_000


def test_failed_carousel_ocr_settles_every_attempted_visual_cost(monkeypatch):
    from uuid import uuid4
    import app.pipeline as pipeline

    settled = []
    jobs = []
    slides = SlideInfo("Recipe", "", None, ["https://cdn.example/1.jpg"], total_image_count=1)
    monkeypatch.setattr(pipeline, "detect_platform", lambda url: Platform.tiktok)
    monkeypatch.setattr(pipeline, "fetch_tiktok_slides", lambda url: slides)

    def fail_ocr(info, *, on_attempt):
        on_attempt()
        raise extract.ExtractError("Incomplete TikTok carousel: unreadable slides 1")

    monkeypatch.setattr(pipeline, "ocr_slides", fail_ocr)
    monkeypatch.setattr(pipeline, "update_job", lambda *args, **kwargs: jobs.append(kwargs))
    monkeypatch.setattr(pipeline, "settle_spend", lambda **kwargs: settled.append(kwargs))
    monkeypatch.setattr(pipeline, "release_job", lambda *args: None)

    pipeline.run_extract_job(uuid4(), uuid4(), "https://www.tiktok.com/@cook/photo/1", "tiktok:1", "en-US")

    assert jobs[-1]["status"] == "failed"
    assert jobs[-1]["error"].startswith("Incomplete TikTok carousel:")
    assert settled[-1]["actual_cents"] == estimate_miss_cost_cents(slide_count=1)


def test_photo_without_complete_slide_hydration_never_falls_back_to_video_metadata(monkeypatch):
    from uuid import uuid4
    import app.pipeline as pipeline

    jobs = []
    settled = []
    monkeypatch.setattr(pipeline, "detect_platform", lambda url: Platform.tiktok)
    monkeypatch.setattr(pipeline, "fetch_tiktok_slides", lambda url: None)
    monkeypatch.setattr(
        pipeline,
        "fetch_media_info",
        lambda url: pytest.fail("photo carousel must not enter video metadata pipeline"),
    )
    monkeypatch.setattr(pipeline, "update_job", lambda *args, **kwargs: jobs.append(kwargs))
    monkeypatch.setattr(pipeline, "settle_spend", lambda **kwargs: settled.append(kwargs))
    monkeypatch.setattr(pipeline, "release_job", lambda *args: None)

    pipeline.run_extract_job(
        uuid4(),
        uuid4(),
        "https://www.tiktok.com/@cook/photo/1",
        "tiktok:photo:1",
        "en-US",
    )

    assert jobs[-1]["status"] == "failed"
    assert jobs[-1]["error"].startswith("Incomplete TikTok carousel:")
    assert settled[-1]["actual_cents"] == 0


def test_tiktok_video_without_caption_uses_three_bounded_frames(monkeypatch, tmp_path):
    from uuid import uuid4
    import app.pipeline as pipeline
    from app.models import Ingredient, IngredientSection, Recipe, Step

    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    paths = []
    for index in range(3):
        path = frame_dir / f"{index}.jpg"
        path.write_bytes(b"frame")
        paths.append(path)
    media = extract.MediaInfo(
        title="Quick dinner",
        description="Short caption",
        author="cook",
        thumbnail_url=None,
        duration_seconds=30,
        webpage_url="https://www.tiktok.com/@cook/video/1",
        subtitles_text="mix eggs",
        audio_path=None,
        media_id="1",
    )
    built = []
    settled = []
    recipe_id = uuid4()
    monkeypatch.setattr(pipeline, "detect_platform", lambda url: Platform.tiktok)
    monkeypatch.setattr(pipeline, "fetch_tiktok_slides", lambda url: None)
    monkeypatch.setattr(pipeline, "fetch_media_info", lambda url: media)
    monkeypatch.setattr(
        pipeline,
        "download_tiktok_video_frames",
        lambda *args, **kwargs: extract.VideoFrames(paths, frame_dir),
    )

    def fake_ocr(frame_paths, *, on_attempt):
        for _ in frame_paths:
            on_attempt()
        return "Frame 1 ingredients\n\nFrame 2 method\n\nFrame 3 serving"

    def fake_build(**kwargs):
        built.append(kwargs)
        ingredient = Ingredient(name="egg")
        return Recipe(
            title="Eggs",
            ingredients=[ingredient],
            ingredient_sections=[IngredientSection(title="Ingredients", ingredients=[ingredient])],
            steps=[Step(order=1, text="Cook")],
            source_url=kwargs["source_url"],
            platform=Platform.tiktok,
        )

    monkeypatch.setattr(pipeline, "ocr_video_frames", fake_ocr)
    monkeypatch.setattr(pipeline, "build_recipe", fake_build)
    monkeypatch.setattr(pipeline, "update_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "upsert_recipe", lambda *args, **kwargs: {"id": str(recipe_id)})
    monkeypatch.setattr(pipeline, "save_user_recipe", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline, "record_usage", lambda **kwargs: None)
    monkeypatch.setattr(pipeline, "settle_spend", lambda **kwargs: settled.append(kwargs))
    monkeypatch.setattr(pipeline, "release_job", lambda *args: None)

    pipeline.run_extract_job(uuid4(), uuid4(), media.webpage_url, "tiktok:video:1", "en-US")

    assert built[0]["slide_text"].endswith("Frame 3 serving")
    assert settled[-1]["actual_cents"] == estimate_miss_cost_cents(frame_count=3)
    assert not frame_dir.exists()


def test_tiktok_metadata_fallback_is_available_when_ytdlp_fails():
    original_run = extract._run_ytdlp
    original_oembed = extract._fetch_tiktok_oembed
    original_validate = extract.validate_public_url
    extract._run_ytdlp = lambda *args, **kwargs: (_ for _ in ()).throw(extract.ExtractError("yt-dlp unavailable"))
    extract.validate_public_url = lambda *args, **kwargs: None
    extract._fetch_tiktok_oembed = lambda url: extract.MediaInfo(
        title="Crispy chicken",
        description="",
        author="cook",
        thumbnail_url=None,
        duration_seconds=None,
        webpage_url=url,
        subtitles_text=None,
        audio_path=None,
    )
    try:
        result = extract.fetch_media_info("https://www.tiktok.com/@cook/video/1")
    finally:
        extract._run_ytdlp = original_run
        extract._fetch_tiktok_oembed = original_oembed
        extract.validate_public_url = original_validate
    assert result.title == "Crispy chicken"


def test_ytdlp_runs_from_active_python_environment():
    original_run = extract.subprocess.run
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")

    extract.subprocess.run = fake_run
    try:
        extract._run_ytdlp(["--version"], timeout=7)
    finally:
        extract.subprocess.run = original_run

    assert calls[0][0][:3] == [extract.sys.executable, "-m", "yt_dlp"]
    assert calls[0][1]["timeout"] == 7


def test_provider_error_payload_is_not_saved_as_job_error():
    error = extract.ExtractError(
        "Error code: 401 - Incorrect API key provided: sk-proj-secret"
    )
    assert _safe_job_error(error) == "Extraction temporarily failed. Retry the import."


def test_tiktok_metadata_fallback_is_available_when_ytdlp_json_is_invalid():
    original_run = extract._run_ytdlp
    original_oembed = extract._fetch_tiktok_oembed
    original_validate = extract.validate_public_url
    extract._run_ytdlp = lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stdout="{invalid",
        stderr="",
    )
    extract.validate_public_url = lambda *args, **kwargs: None
    extract._fetch_tiktok_oembed = lambda url: extract.MediaInfo(
        title="Pasta bake",
        description="",
        author="cook",
        thumbnail_url=None,
        duration_seconds=None,
        webpage_url=url,
        subtitles_text=None,
        audio_path=None,
    )
    try:
        result = extract.fetch_media_info("https://www.tiktok.com/@cook/video/2")
    finally:
        extract._run_ytdlp = original_run
        extract._fetch_tiktok_oembed = original_oembed
        extract.validate_public_url = original_validate
    assert result.title == "Pasta bake"


def test_audio_download_failure_does_not_discard_valid_metadata():
    original_run = extract._run_ytdlp
    original_download = extract._download_audio
    original_validate = extract.validate_public_url
    extract._run_ytdlp = lambda *args, **kwargs: SimpleNamespace(
        returncode=0,
        stdout='{"id":"video-1","title":"Quick eggs","description":"Pan recipe"}',
        stderr="",
    )
    extract._download_audio = lambda *args, **kwargs: (_ for _ in ()).throw(
        extract.ExtractError("audio timeout")
    )
    extract.validate_public_url = lambda *args, **kwargs: None
    try:
        result = extract.fetch_media_info("https://www.youtube.com/watch?v=video-1")
    finally:
        extract._run_ytdlp = original_run
        extract._download_audio = original_download
        extract.validate_public_url = original_validate
    assert result.title == "Quick eggs"
    assert result.audio_path is None


def test_recipe_builder_preserves_ordered_carousel_metadata():
    original_client = recipe_builder.OpenAI
    original_key = recipe_builder.settings.openai_api_key

    class FakeCompletions:
        def create(self, **kwargs):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"title":"Pasta","description":"Fast dinner",'
                                '"ingredient_sections":[{"title":"Ingredients",'
                                '"ingredients":[{"name":"pasta","quantity":"250","unit":"g"}]}],'
                                '"tips":[],"steps":[{"order":1,"text":"Boil","duration_minutes":10}],'
                                '"servings":2,"prep_minutes":5,"cook_minutes":10,"tags":[],'
                                '"confidence":0.9,"missing_fields":[]}'
                            ),
                            refusal=None,
                        ),
                        finish_reason="stop",
                    )
                ]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    recipe_builder.OpenAI = FakeClient
    recipe_builder.settings.openai_api_key = "test-key"
    try:
        result = recipe_builder.build_recipe(
            platform=Platform.tiktok,
            source_url="https://www.tiktok.com/@cook/photo/1",
            title="Pasta",
            description="Fast dinner",
            author="cook",
            thumbnail_url="https://cdn.example/slide-1.jpg",
            carousel_image_urls=[
                "https://cdn.example/slide-1.jpg",
                "https://cdn.example/slide-2.jpg",
            ],
            transcript=None,
            slide_text="Boil pasta",
        )
    finally:
        recipe_builder.OpenAI = original_client
        recipe_builder.settings.openai_api_key = original_key

    assert result.carousel_image_urls == [
        "https://cdn.example/slide-1.jpg",
        "https://cdn.example/slide-2.jpg",
    ]
