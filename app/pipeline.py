from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from app.config import settings
from app.extract import ExtractError, fetch_media_info
from app.models import JobStatus, Platform, Recipe
from app.platforms import detect_platform
from app.recipe_builder import build_recipe
from app.tiktok_slides import SlideInfo, fetch_tiktok_slides
from app.transcript import ocr_slides, whisper_transcript, youtube_transcript


@dataclass
class JobRecord:
    job_id: UUID
    status: JobStatus
    recipe: Recipe | None = None
    error: str | None = None
    created_at: float = 0.0


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[UUID, JobRecord] = {}

    def create(self) -> JobRecord:
        self._purge_old()
        job = JobRecord(job_id=uuid4(), status=JobStatus.pending, created_at=time.time())
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: UUID) -> JobRecord | None:
        self._purge_old()
        return self._jobs.get(job_id)

    def _purge_old(self) -> None:
        cutoff = time.time() - settings.job_ttl_seconds
        expired = [jid for jid, job in self._jobs.items() if job.created_at < cutoff]
        for jid in expired:
            self._jobs.pop(jid, None)


jobs = JobStore()


def run_extract_job(job_id: UUID, url: str) -> None:
    record = jobs.get(job_id)
    if not record:
        return

    record.status = JobStatus.processing
    audio_path: Path | None = None

    try:
        platform = detect_platform(url)
        if platform == Platform.unknown:
            raise ExtractError("Unsupported URL. Use TikTok, YouTube, Instagram or Facebook.")

        slide_info: SlideInfo | None = None
        if platform == Platform.tiktok:
            slide_info = fetch_tiktok_slides(url)

        if slide_info and slide_info.image_urls:
            slide_text = ocr_slides(slide_info)
            record.recipe = build_recipe(
                platform=platform,
                source_url=url,
                title=slide_info.title,
                description=slide_info.description,
                author=slide_info.author,
                thumbnail_url=slide_info.image_urls[0],
                transcript=None,
                slide_text=slide_text,
            )
            record.status = JobStatus.completed
            return

        media = fetch_media_info(url)
        audio_path = media.audio_path

        transcript = media.subtitles_text
        if not transcript and platform == Platform.youtube:
            transcript = youtube_transcript(url)
        if not transcript and audio_path:
            transcript = whisper_transcript(audio_path)
        if not transcript and not media.description:
            raise ExtractError("No transcript, subtitles or description found")

        record.recipe = build_recipe(
            platform=platform,
            source_url=media.webpage_url,
            title=media.title,
            description=media.description,
            author=media.author,
            thumbnail_url=media.thumbnail_url,
            transcript=transcript,
            slide_text=media.extra_text,
        )
        record.status = JobStatus.completed
    except ExtractError as exc:
        record.status = JobStatus.failed
        record.error = str(exc)
    except Exception as exc:
        record.status = JobStatus.failed
        record.error = f"Unexpected error: {exc}"
    finally:
        if audio_path:
            shutil.rmtree(audio_path.parent, ignore_errors=True)
