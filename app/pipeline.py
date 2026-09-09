from __future__ import annotations

import shutil
import logging
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from app.config import settings
from app.costing import estimate_miss_cost_cents
from app.extract import ExtractError, VideoFrames, download_tiktok_video_frames, fetch_media_info
from app.models import JobStatus, Platform, Recipe
from app.platforms import detect_platform
from app.quota import record_usage
from app.job_guard import release as release_job
from app.localization import normalize_language
from app.spend import conservative_failure_cost, settle_spend
from app.recipe_builder import build_recipe, translate_recipe
from app.store import get_recipe, recipe_from_row, save_user_recipe, update_job, upsert_recipe
from app.translation_cache import (
    recipe_translation_payload,
    source_recipe_fingerprint,
    upsert_recipe_translation,
)
from app.tiktok_slides import SlideInfo, fetch_tiktok_slides
from app.transcript import ocr_slides, ocr_video_frames, whisper_transcript, youtube_transcript

logger = logging.getLogger(__name__)
_RETRYABLE_EXTRACTION_ERROR = "Extraction temporarily failed. Retry the import."


def _safe_job_error(error: ExtractError) -> str:
    """Keep user-facing job errors stable and free of provider payloads."""
    message = str(error).strip()
    safe_prefixes = (
        "Unsupported URL.",
        "Video too long (",
        "No usable recipe text found in source",
        "Incomplete TikTok carousel:",
        "TikTok video evidence incomplete:",
        "Recipe source text exceeds supported bound",
        "OPENAI_API_KEY is not configured",
        "Recipe model refused",
        "Recipe model returned",
        "Recipe output failed validation",
        "Translated recipe output failed validation",
        "Recipe not found for translation",
    )
    if message.startswith(safe_prefixes):
        return message[:300]
    return _RETRYABLE_EXTRACTION_ERROR


def run_extract_job(job_id: UUID, user_id: UUID, url: str, url_norm: str, language_code: str) -> None:
    if settings.maintenance_mode:
        # Keep the durable job pending; release only the process-local slot.
        # Operators must drain already-running jobs before backup/reset.
        release_job(user_id)
        return
    language_code = normalize_language(language_code)
    audio_path: Path | None = None
    used_transcribe = False
    slide_count = 0
    frame_count = 0
    duration_seconds: int | None = None
    openai_called = False
    estimated_cost = 0.0
    video_frames: VideoFrames | None = None

    def record_ocr_attempt() -> None:
        nonlocal frame_count, slide_count, estimated_cost, openai_called
        openai_called = True
        if slide_info is not None:
            slide_count += 1
        else:
            frame_count += 1
        estimated_cost = estimate_miss_cost_cents(
            duration_seconds=duration_seconds,
            slide_count=slide_count,
            frame_count=frame_count,
            used_transcribe=used_transcribe,
        )

    try:
        update_job(job_id, status=JobStatus.processing.value, progress=5)
        platform = detect_platform(url)
        logger.info("extract stage=platform job_id=%s platform=%s", job_id, platform.value)
        update_job(job_id, progress=15)
        if platform == Platform.unknown:
            raise ExtractError("Unsupported URL. Use TikTok, YouTube, Instagram or Facebook.")

        slide_info: SlideInfo | None = None
        if platform == Platform.tiktok:
            slide_info = fetch_tiktok_slides(url)
            logger.info(
                "extract stage=slides job_id=%s platform=%s slide_count=%d",
                job_id,
                platform.value,
                len(slide_info.image_urls) if slide_info else 0,
            )
            update_job(job_id, progress=30)
            if slide_info is None and "/photo/" in (urlparse(url).path or "").lower():
                raise ExtractError(
                    "Incomplete TikTok carousel: complete slide hydration was unavailable"
                )

        recipe: Recipe
        if slide_info and slide_info.image_urls:
            if slide_info.incomplete_reason:
                raise ExtractError(f"Incomplete TikTok carousel: {slide_info.incomplete_reason}")
            slide_text = ocr_slides(slide_info, on_attempt=record_ocr_attempt)
            update_job(job_id, progress=60)
            openai_called = True
            estimated_cost = estimate_miss_cost_cents(slide_count=slide_count)
            recipe = build_recipe(
                platform=platform,
                source_url=url,
                title=slide_info.title,
                description=slide_info.description,
                author=slide_info.author,
                thumbnail_url=slide_info.image_urls[0],
                carousel_image_urls=slide_info.image_urls,
                transcript=None,
                slide_text=slide_text,
                language_code=language_code,
            )
        else:
            media = fetch_media_info(url)
            logger.info(
                "extract stage=media job_id=%s platform=%s duration_seconds=%s subtitles=%s audio=%s",
                job_id,
                platform.value,
                media.duration_seconds,
                bool(media.subtitles_text),
                bool(media.audio_path),
            )
            update_job(job_id, progress=30)
            audio_path = media.audio_path
            duration_seconds = media.duration_seconds

            transcript = media.subtitles_text
            if not transcript and platform == Platform.youtube:
                transcript = youtube_transcript(url)
            if not transcript and audio_path:
                openai_called = True
                used_transcribe = True
                estimated_cost = estimate_miss_cost_cents(
                    duration_seconds=duration_seconds,
                    used_transcribe=True,
                )
                try:
                    transcript = whisper_transcript(audio_path)
                except Exception as exc:
                    # Continue with title/description instead of converting a
                    # missing audio transcript into a permanently failed job.
                    logger.warning(
                        "extract stage=whisper_fallback job_id=%s platform=%s error_type=%s",
                        job_id,
                        platform.value,
                        type(exc).__name__,
                    )
                    transcript = None
            video_text = media.extra_text
            if (
                platform == Platform.tiktok
                and not _has_sufficient_recipe_evidence(
                    transcript,
                    media.title,
                    media.description,
                    video_text,
                )
            ):
                try:
                    video_frames = download_tiktok_video_frames(
                        url,
                        media_id=media.media_id,
                        duration_seconds=duration_seconds,
                    )
                    openai_called = True
                    video_text = ocr_video_frames(video_frames.paths, on_attempt=record_ocr_attempt)
                except ExtractError as exc:
                    # Caption/oEmbed text can still yield a recipe when the
                    # datacenter cannot download TikTok media.
                    logger.warning(
                        "extract stage=frame_fallback job_id=%s error_type=%s",
                        job_id,
                        type(exc).__name__,
                    )
            update_job(job_id, progress=60)
            if not transcript and not any(
                text.strip() for text in (media.title, media.description, video_text or "")
            ):
                raise ExtractError("No usable recipe text found in source")

            openai_called = True
            recipe = build_recipe(
                platform=platform,
                source_url=media.webpage_url,
                title=media.title,
                description=media.description,
                author=media.author,
                thumbnail_url=media.thumbnail_url,
                transcript=transcript,
                slide_text=video_text,
                language_code=language_code,
            )
        update_job(job_id, progress=85)

        row = upsert_recipe(recipe, source_url_norm=url_norm, language_code=language_code)
        recipe_id = UUID(row["id"])
        logger.info(
            "extract stage=persisted job_id=%s platform=%s recipe_id=%s slide_count=%d transcribed=%s",
            job_id,
            platform.value,
            recipe_id,
            slide_count,
            used_transcribe,
        )
        cost = estimate_miss_cost_cents(
            duration_seconds=duration_seconds,
            slide_count=slide_count,
            frame_count=frame_count,
            used_transcribe=used_transcribe,
        )
        estimated_cost = cost
        save_user_recipe(user_id, recipe_id)
        update_job(
            job_id,
            status=JobStatus.completed.value,
            progress=100,
            lease_until=None,
            recipe_id=recipe_id,
            cost_cents=cost,
            cache_hit=False,
        )
        # Recipe/job completion is the user-visible critical path. A temporary
        # usage-event failure must not turn a saved recipe into a failed job.
        try:
            record_usage(
                user_id=user_id,
                kind="extract_miss",
                cost_cents=cost,
                recipe_id=recipe_id,
                job_id=job_id,
            )
        except Exception:
            pass
        settle_spend(job_id=job_id, actual_cents=cost, status="settled")
    except ExtractError as exc:
        logger.warning(
            "extract failed job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
        )
        _mark_job_failed(job_id, _safe_job_error(exc))
        settle_spend(
            job_id=job_id,
            actual_cents=conservative_failure_cost(openai_called=openai_called, estimated_cents=estimated_cost),
            status="failed",
        )
    except Exception as exc:
        logger.error(
            "extract failed job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
        )
        _mark_job_failed(job_id, _RETRYABLE_EXTRACTION_ERROR)
        settle_spend(
            job_id=job_id,
            actual_cents=conservative_failure_cost(openai_called=openai_called, estimated_cents=estimated_cost),
            status="failed",
        )
    finally:
        release_job(user_id)
        if audio_path:
            shutil.rmtree(audio_path.parent, ignore_errors=True)
        if video_frames:
            shutil.rmtree(video_frames.directory, ignore_errors=True)


def _has_sufficient_recipe_evidence(*parts: str | None) -> bool:
    """Use frames when all available transcript/caption evidence is too sparse."""
    words = " ".join(part.strip() for part in parts if part and part.strip()).split()
    return len(words) >= 80


def _mark_job_failed(job_id: UUID, error: str) -> None:
    try:
        update_job(
            job_id,
            status=JobStatus.failed.value,
            progress=0,
            lease_until=None,
            error=error[:1000],
        )
    except Exception:
        # Preserve original extraction failure; the job may be recovered by TTL.
        pass


def run_translation_job(job_id: UUID, user_id: UUID, recipe_id: UUID, language_code: str) -> None:
    if settings.maintenance_mode:
        # Keep the durable job pending; release only the process-local slot.
        # Operators must drain already-running jobs before backup/reset.
        release_job(user_id)
        return
    language_code = normalize_language(language_code)
    openai_called = False
    estimated_cost = 0.0
    try:
        update_job(job_id, status=JobStatus.processing.value, progress=10)
        row = get_recipe(recipe_id)
        if not row:
            raise ExtractError("Recipe not found for translation")
        base_recipe = recipe_from_row(row)
        source_fingerprint = source_recipe_fingerprint(row)
        if normalize_language(row.get("language_code")) == language_code:
            payload = recipe_translation_payload(base_recipe)
        else:
            openai_called = True
            translated = translate_recipe(base_recipe, language_code)
            payload = recipe_translation_payload(translated)
        estimated_cost = estimate_miss_cost_cents()
        update_job(job_id, progress=75)
        upsert_recipe_translation(
            recipe_id,
            language_code,
            payload,
            source_fingerprint=source_fingerprint,
        )
        save_user_recipe(user_id, recipe_id)
        update_job(
            job_id,
            status=JobStatus.completed.value,
            progress=100,
            lease_until=None,
            recipe_id=recipe_id,
            cost_cents=estimated_cost if openai_called else 0,
            cache_hit=not openai_called,
        )
        if openai_called:
            try:
                record_usage(
                    user_id=user_id,
                    kind="extract_miss",
                    cost_cents=estimated_cost,
                    recipe_id=recipe_id,
                    job_id=job_id,
                )
            except Exception:
                pass
        settle_spend(
            job_id=job_id,
            actual_cents=estimated_cost if openai_called else 0,
            status="settled",
        )
    except ExtractError as exc:
        logger.warning(
            "translation failed job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
        )
        _mark_job_failed(job_id, _safe_job_error(exc))
        settle_spend(
            job_id=job_id,
            actual_cents=conservative_failure_cost(openai_called=openai_called, estimated_cents=estimated_cost),
            status="failed",
        )
    except Exception as exc:
        logger.error(
            "translation failed job_id=%s error_type=%s",
            job_id,
            type(exc).__name__,
        )
        _mark_job_failed(job_id, _RETRYABLE_EXTRACTION_ERROR)
        settle_spend(
            job_id=job_id,
            actual_cents=conservative_failure_cost(openai_called=openai_called, estimated_cents=estimated_cost),
            status="failed",
        )
    finally:
        release_job(user_id)
