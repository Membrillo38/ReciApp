import json
from types import SimpleNamespace
from pathlib import Path

import app.recipe_builder as recipe_builder
import app.extract as extract
from app.costing import estimate_miss_cost_cents
from app.config import settings
from app.pipeline import _safe_job_error
from app.models import Platform
from app.tiktok_slides import _dig_item_struct, _image_urls, _photo_meta_fallback, fetch_tiktok_slides


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


def test_ocr_processes_all_bounded_slides_and_skips_one_failed_slide():
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
        result = transcript.ocr_slides(
            SlideInfo(
                title="Carousel",
                description="",
                author=None,
                image_urls=[f"https://cdn.example/slide-{i}.jpg" for i in range(1, 13)],
            )
        )
    finally:
        transcript.download_image_b64 = original_download
        transcript.OpenAI = original_client
        transcript.settings.openai_api_key = original_key

    assert len(requested) == MAX_CAROUSEL_SLIDES
    assert len(model_calls) == MAX_CAROUSEL_SLIDES - 1
    assert result.count("ingredient") == MAX_CAROUSEL_SLIDES - 2


def test_carousel_cost_accounts_for_all_bounded_ocr_slides():
    from app.tiktok_slides import MAX_CAROUSEL_SLIDES

    expected = round(
        settings.cost_text_cents_per_extract
        + MAX_CAROUSEL_SLIDES * settings.cost_ocr_cents_per_slide,
        4,
    )
    assert estimate_miss_cost_cents(slide_count=MAX_CAROUSEL_SLIDES) == expected
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
    assert 'extract stage=ocr_fallback' in source
    assert 'extract stage=whisper_fallback' in source
    assert 'extract stage=persisted' in source
    assert 'logger.warning("recipe_model attempt=%d error_type=%s"' not in source
    assert 'f"Unexpected error: {exc}"' not in source
    assert "_RETRYABLE_EXTRACTION_ERROR" in source


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
