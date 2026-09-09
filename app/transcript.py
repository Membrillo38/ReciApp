from __future__ import annotations

import logging
import base64
from pathlib import Path
from typing import Callable

from openai import OpenAI
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.config import settings
from app.extract import ExtractError
from app.platforms import youtube_video_id
from app.tiktok_slides import MAX_CAROUSEL_SLIDES, SlideInfo, download_image_b64

logger = logging.getLogger(__name__)


def youtube_transcript(url: str) -> str | None:
    video_id = youtube_video_id(url)
    if not video_id:
        return None

    languages = ["es", "es-ES", "en", "en-US"]
    try:
        fetched = YouTubeTranscriptApi.get_transcript(video_id, languages=languages)
    except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
        return None
    except Exception:
        return None

    parts = [entry.get("text", "").strip() for entry in fetched if entry.get("text")]
    text = " ".join(parts).strip()
    return text or None


def whisper_transcript(audio_path: Path) -> str:
    """Transcribe audio via OpenAI Transcriptions API (gpt-4o-mini-transcribe)."""
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    with audio_path.open("rb") as audio_file:
        result = client.audio.transcriptions.create(
            model=settings.transcribe_model,
            file=audio_file,
            response_format="text",
        )
    text = str(result).strip()
    if not text:
        raise ExtractError("Transcription returned empty text")
    return text


def _ocr_image(
    client: OpenAI,
    *,
    b64: str,
    label: str,
    on_attempt: Callable[[], None] | None,
) -> str:
    if on_attempt:
        on_attempt()
    response = client.chat.completions.create(
        model=settings.vision_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"{label}. Extract all visible recipe text: section headings, "
                            "ingredients, quantities, steps, times, and tips. Preserve headings "
                            "such as component names and storage/reheating tips. Return concise "
                            "plain text only. Skip decorative slogans and engagement text."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
        max_tokens=500,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ExtractError(f"{label} OCR returned no result")
    choice = choices[0]
    if getattr(choice, "finish_reason", None) == "length":
        raise ExtractError(f"{label} OCR output was truncated")
    message = getattr(choice, "message", None)
    chunk = (getattr(message, "content", None) or "").strip()
    if not chunk:
        raise ExtractError(f"{label} OCR returned empty text")
    return chunk


def ocr_slides(
    slides: SlideInfo,
    max_images: int = MAX_CAROUSEL_SLIDES,
    *,
    on_attempt: Callable[[], None] | None = None,
) -> str:
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    limit = min(max_images, MAX_CAROUSEL_SLIDES)
    if slides.incomplete_reason:
        raise ExtractError(f"Incomplete TikTok carousel: {slides.incomplete_reason}")
    if slides.total_image_count > limit or len(slides.image_urls) > limit:
        raise ExtractError(
            f"Incomplete TikTok carousel: supported limit is {limit} slides"
        )
    parts: list[str] = []
    failures: list[int] = []

    for idx, url in enumerate(slides.image_urls, start=1):
        try:
            b64 = download_image_b64(url)
        except Exception as exc:
            logger.warning(
                "extract stage=ocr_slide_download slide_index=%d error_type=%s",
                idx,
                type(exc).__name__,
            )
            failures.append(idx)
            continue
        if not b64:
            failures.append(idx)
            continue
        try:
            parts.append(
                _ocr_image(
                    client,
                    b64=b64,
                    label=f"Slide {idx}",
                    on_attempt=on_attempt,
                )
            )
        except Exception as exc:
            logger.warning(
                "extract stage=ocr_slide_model slide_index=%d error_type=%s",
                idx,
                type(exc).__name__,
            )
            failures.append(idx)

    if failures:
        indexes = ",".join(str(index) for index in failures)
        raise ExtractError(f"Incomplete TikTok carousel: unreadable slides {indexes}")
    merged = "\n\n".join(parts).strip()
    if not merged:
        raise ExtractError("Could not OCR slideshow images")
    return merged


def ocr_video_frames(
    frame_paths: list[Path],
    *,
    on_attempt: Callable[[], None] | None = None,
) -> str:
    """OCR up to three sampled frames; this is a bounded fallback, not full coverage."""
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")
    if not frame_paths or len(frame_paths) > 3:
        raise ExtractError("TikTok video frame fallback returned an invalid frame set")

    client = OpenAI(api_key=settings.openai_api_key)
    parts: list[str] = []
    for idx, path in enumerate(frame_paths, start=1):
        try:
            raw = path.read_bytes()
            if not raw or len(raw) > 2_000_000:
                raise ExtractError(f"Video frame {idx} has an invalid size")
            parts.append(
                _ocr_image(
                    client,
                    b64=base64.b64encode(raw).decode("ascii"),
                    label=f"Sampled video frame {idx}",
                    on_attempt=on_attempt,
                )
            )
        except Exception as exc:
            logger.warning(
                "extract stage=ocr_video_frame frame_index=%d error_type=%s",
                idx,
                type(exc).__name__,
            )
            raise ExtractError(
                f"TikTok video evidence incomplete: sampled frame {idx} could not be read"
            ) from exc
    return "\n\n".join(parts)
