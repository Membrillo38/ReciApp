from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID

from app.costing import estimate_miss_cost_cents
from app.extract import ExtractError, fetch_media_info
from app.models import JobStatus, Platform, Recipe
from app.platforms import detect_platform
from app.quota import record_usage
from app.recipe_builder import build_recipe
from app.store import save_user_recipe, update_job, upsert_recipe
from app.tiktok_slides import SlideInfo, fetch_tiktok_slides
from app.transcript import ocr_slides, whisper_transcript, youtube_transcript


def run_extract_job(job_id: UUID, user_id: UUID, url: str, url_norm: str) -> None:
    update_job(job_id, status=JobStatus.processing.value)
    audio_path: Path | None = None
    used_transcribe = False
    slide_count = 0
    duration_seconds: int | None = None

    try:
        platform = detect_platform(url)
        if platform == Platform.unknown:
            raise ExtractError("Unsupported URL. Use TikTok, YouTube, Instagram or Facebook.")

        slide_info: SlideInfo | None = None
        if platform == Platform.tiktok:
            slide_info = fetch_tiktok_slides(url)

        recipe: Recipe
        if slide_info and slide_info.image_urls:
            slide_count = len(slide_info.image_urls)
            slide_text = ocr_slides(slide_info)
            recipe = build_recipe(
                platform=platform,
                source_url=url,
                title=slide_info.title,
                description=slide_info.description,
                author=slide_info.author,
                thumbnail_url=slide_info.image_urls[0],
                transcript=None,
                slide_text=slide_text,
            )
        else:
            media = fetch_media_info(url)
            audio_path = media.audio_path
            duration_seconds = media.duration_seconds

            transcript = media.subtitles_text
            if not transcript and platform == Platform.youtube:
                transcript = youtube_transcript(url)
            if not transcript and audio_path:
                transcript = whisper_transcript(audio_path)
                used_transcribe = True
            if not transcript and not media.description:
                raise ExtractError("No transcript, subtitles or description found")

            recipe = build_recipe(
                platform=platform,
                source_url=media.webpage_url,
                title=media.title,
                description=media.description,
                author=media.author,
                thumbnail_url=media.thumbnail_url,
                transcript=transcript,
                slide_text=media.extra_text,
            )

        row = upsert_recipe(recipe, source_url_norm=url_norm)
        recipe_id = UUID(row["id"])
        cost = estimate_miss_cost_cents(
            duration_seconds=duration_seconds,
            slide_count=slide_count,
            used_transcribe=used_transcribe,
        )
        save_user_recipe(user_id, recipe_id)
        update_job(
            job_id,
            status=JobStatus.completed.value,
            recipe_id=recipe_id,
            cost_cents=cost,
            cache_hit=False,
        )
        record_usage(
            user_id=user_id,
            kind="extract_miss",
            cost_cents=cost,
            recipe_id=recipe_id,
            job_id=job_id,
        )
    except ExtractError as exc:
        update_job(job_id, status=JobStatus.failed.value, error=str(exc))
    except Exception as exc:
        update_job(job_id, status=JobStatus.failed.value, error=f"Unexpected error: {exc}")
    finally:
        if audio_path:
            shutil.rmtree(audio_path.parent, ignore_errors=True)
