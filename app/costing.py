from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Iterator

from app.config import settings
from app.tiktok_slides import MAX_CAROUSEL_SLIDES

_current_meter: ContextVar["JobCostMeter | None"] = ContextVar("job_cost_meter", default=None)


@dataclass
class JobCostMeter:
    """Accumulate OpenAI usage for one extract/translation job."""

    cents: float = 0.0
    openai_called: bool = False
    chat_calls: int = 0
    transcribe_calls: int = 0
    vision_frames: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    def add_chat(
        self,
        response: Any,
        *,
        fallback_cents: float | None = None,
        frames: int = 0,
    ) -> float:
        self.openai_called = True
        self.chat_calls += 1
        if frames:
            self.vision_frames += frames
        usage = getattr(response, "usage", None)
        added = _chat_usage_cents(usage)
        if added is None:
            added = float(fallback_cents or settings.cost_text_cents_per_extract)
            if frames:
                added = max(
                    added,
                    frames * settings.cost_ocr_cents_per_slide,
                )
        self.cents = round(self.cents + added, 4)
        self.details.append({"kind": "chat", "cents": added, "frames": frames})
        return added

    def add_transcription(
        self,
        response: Any,
        *,
        duration_seconds: float | None = None,
        fallback_cents: float | None = None,
    ) -> float:
        self.openai_called = True
        self.transcribe_calls += 1
        usage = getattr(response, "usage", None)
        added = _transcribe_usage_cents(usage, duration_seconds=duration_seconds)
        if added is None:
            minutes = max((duration_seconds or 60) / 60.0, 0.25)
            added = float(
                fallback_cents
                if fallback_cents is not None
                else minutes * settings.cost_transcribe_cents_per_min
            )
        self.cents = round(self.cents + added, 4)
        self.details.append({"kind": "transcribe", "cents": added})
        return added

    def add_fallback(self, cents: float, *, kind: str = "fallback") -> float:
        added = max(float(cents), 0.0)
        if added <= 0:
            return 0.0
        self.openai_called = True
        self.cents = round(self.cents + added, 4)
        self.details.append({"kind": kind, "cents": added})
        return added


def get_cost_meter() -> JobCostMeter | None:
    return _current_meter.get()


@contextmanager
def cost_meter_scope(meter: JobCostMeter | None = None) -> Iterator[JobCostMeter]:
    active = meter or JobCostMeter()
    token = _current_meter.set(active)
    try:
        yield active
    finally:
        _current_meter.reset(token)


def record_chat_usage(
    response: Any,
    *,
    fallback_cents: float | None = None,
    frames: int = 0,
) -> float:
    meter = get_cost_meter()
    if meter is None:
        return 0.0
    return meter.add_chat(response, fallback_cents=fallback_cents, frames=frames)


def record_transcription_usage(
    response: Any,
    *,
    duration_seconds: float | None = None,
    fallback_cents: float | None = None,
) -> float:
    meter = get_cost_meter()
    if meter is None:
        return 0.0
    return meter.add_transcription(
        response,
        duration_seconds=duration_seconds,
        fallback_cents=fallback_cents,
    )


def estimate_miss_cost_cents(
    *,
    duration_seconds: int | None = None,
    slide_count: int = 0,
    frame_count: int = 0,
    used_transcribe: bool = False,
) -> float:
    """Worst-case / fallback estimate for spend reservation and missing usage."""
    cost = float(settings.cost_text_cents_per_extract)
    if used_transcribe:
        minutes = max((duration_seconds or 60) / 60.0, 0.25)
        cost += minutes * settings.cost_transcribe_cents_per_min
    if slide_count > 0:
        cost += min(slide_count, MAX_CAROUSEL_SLIDES) * settings.cost_ocr_cents_per_slide
    if frame_count > 0:
        cost += frame_count * settings.cost_ocr_cents_per_slide
    return round(cost, 4)


def _chat_usage_cents(usage: Any) -> float | None:
    if usage is None:
        return None
    prompt = _int_attr(usage, "prompt_tokens", "input_tokens")
    completion = _int_attr(usage, "completion_tokens", "output_tokens")
    if prompt is None and completion is None:
        return None
    prompt = prompt or 0
    completion = completion or 0
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None) or getattr(
        usage, "input_tokens_details", None
    )
    if details is not None:
        cached = _int_attr(details, "cached_tokens") or 0
    cached = min(cached, prompt)
    uncached = max(prompt - cached, 0)
    dollars = (
        (uncached / 1_000_000.0) * settings.openai_chat_input_usd_per_mtok
        + (cached / 1_000_000.0) * settings.openai_chat_cached_input_usd_per_mtok
        + (completion / 1_000_000.0) * settings.openai_chat_output_usd_per_mtok
    )
    return round(dollars * 100.0, 4)


def _transcribe_usage_cents(
    usage: Any,
    *,
    duration_seconds: float | None,
) -> float | None:
    if usage is not None:
        input_tokens = _int_attr(usage, "input_tokens", "prompt_tokens")
        output_tokens = _int_attr(usage, "output_tokens", "completion_tokens")
        audio_tokens = 0
        text_tokens = 0
        details = getattr(usage, "input_token_details", None) or getattr(
            usage, "prompt_tokens_details", None
        )
        if details is not None:
            audio_tokens = _int_attr(details, "audio_tokens") or 0
            text_tokens = _int_attr(details, "text_tokens") or 0
        if input_tokens is not None or output_tokens is not None or audio_tokens or text_tokens:
            input_tokens = input_tokens or 0
            output_tokens = output_tokens or 0
            if audio_tokens or text_tokens:
                billed_input = audio_tokens + text_tokens
            else:
                billed_input = input_tokens
            dollars = (
                (billed_input / 1_000_000.0) * settings.openai_transcribe_input_usd_per_mtok
                + (output_tokens / 1_000_000.0) * settings.openai_transcribe_output_usd_per_mtok
            )
            return round(dollars * 100.0, 4)
        seconds = getattr(usage, "seconds", None)
        if isinstance(seconds, (int, float)) and seconds > 0:
            return round((float(seconds) / 60.0) * settings.openai_transcribe_usd_per_min * 100.0, 4)
    if duration_seconds is not None and duration_seconds > 0:
        return round(
            (float(duration_seconds) / 60.0) * settings.openai_transcribe_usd_per_min * 100.0,
            4,
        )
    return None


def _int_attr(obj: Any, *names: str) -> int | None:
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if isinstance(value, (int, float)):
                return int(value)
        return None
    for name in names:
        value = getattr(obj, name, None)
        if isinstance(value, (int, float)):
            return int(value)
    return None
