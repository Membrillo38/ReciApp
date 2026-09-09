from __future__ import annotations

from app.config import settings
from app.extract import MAX_VIDEO_FRAMES
from app.tiktok_slides import MAX_CAROUSEL_SLIDES


def estimate_miss_cost_cents(
    *,
    duration_seconds: int | None = None,
    slide_count: int = 0,
    frame_count: int = 0,
    used_transcribe: bool = False,
) -> float:
    cost = float(settings.cost_text_cents_per_extract)
    if used_transcribe:
        minutes = max((duration_seconds or 60) / 60.0, 0.25)
        cost += minutes * settings.cost_transcribe_cents_per_min
    if slide_count > 0:
        cost += min(slide_count, MAX_CAROUSEL_SLIDES) * settings.cost_ocr_cents_per_slide
    if frame_count > 0:
        cost += min(frame_count, MAX_VIDEO_FRAMES) * settings.cost_ocr_cents_per_slide
    return round(cost, 4)
