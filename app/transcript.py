from __future__ import annotations

from pathlib import Path

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
from app.tiktok_slides import SlideInfo, download_image_b64


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


def ocr_slides(slides: SlideInfo, max_images: int = 8) -> str:
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")

    client = OpenAI(api_key=settings.openai_api_key)
    parts: list[str] = []

    for idx, url in enumerate(slides.image_urls[:max_images], start=1):
        b64 = download_image_b64(url)
        if not b64:
            continue
        response = client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Slide {idx}. Extract all visible recipe text: "
                                "ingredients, quantities, steps, times. "
                                "Return plain text only."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            max_tokens=700,
        )
        chunk = (response.choices[0].message.content or "").strip()
        if chunk:
            parts.append(chunk)

    merged = "\n\n".join(parts).strip()
    if not merged:
        raise ExtractError("Could not OCR slideshow images")
    return merged
