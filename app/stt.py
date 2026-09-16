"""Multi-provider STT rotation. Free/cheap APIs first; local or OpenAI as fallback."""

from __future__ import annotations

import logging
import mimetypes
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from openai import OpenAI

from app.config import settings
from app.costing import estimate_miss_cost_cents, record_transcription_usage
from app.extract import ExtractError
from app.job_guard import active_counts

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_POLL_SEC = 1.5
_POLL_MAX = 90
_rr_lock = threading.Lock()
_rr_index = 0


class SttRateLimited(Exception):
    """Provider rejected due to rate limit / quota."""


class SttBadResult(Exception):
    """Provider returned empty or unusable transcript."""


def _lang(language_code: str | None) -> str | None:
    raw = (language_code or "").strip()
    if not raw:
        return None
    return raw.split("-", 1)[0].lower() or None


def _mime(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _usable(text: str | None) -> str | None:
    cleaned = (text or "").strip()
    return cleaned or None


def _raise_http(provider: str, response: httpx.Response) -> None:
    if response.status_code in {429, 503}:
        raise SttRateLimited(f"{provider} status={response.status_code}")
    if response.status_code in {401, 403}:
        raise SttRateLimited(f"{provider} auth_or_forbidden status={response.status_code}")
    raise ExtractError(f"{provider} STT failed status={response.status_code}")


def _groq(path: Path, *, language_code: str | None) -> str:
    if not settings.groq_api_key:
        raise SttRateLimited("groq missing key")
    client = OpenAI(api_key=settings.groq_api_key, base_url="https://api.groq.com/openai/v1")
    with path.open("rb") as audio_file:
        kwargs: dict = {
            "model": "whisper-large-v3-turbo",
            "file": (path.name, audio_file, _mime(path)),
            "response_format": "json",
        }
        lang = _lang(language_code)
        if lang:
            kwargs["language"] = lang
        try:
            result = client.audio.transcriptions.create(**kwargs)
        except Exception as exc:
            name = type(exc).__name__
            if "RateLimit" in name or "429" in str(exc):
                raise SttRateLimited("groq rate_limit") from exc
            raise
    text = _usable(getattr(result, "text", None) or str(result))
    if not text:
        raise SttBadResult("groq empty")
    return text


def _deepgram(path: Path, *, language_code: str | None) -> str:
    if not settings.deepgram_api_key:
        raise SttRateLimited("deepgram missing key")
    params: dict[str, str] = {"model": "nova-3", "smart_format": "true"}
    lang = _lang(language_code)
    if lang:
        params["language"] = lang
    with path.open("rb") as audio_file:
        response = httpx.post(
            "https://api.deepgram.com/v1/listen",
            params=params,
            headers={
                "Authorization": f"Token {settings.deepgram_api_key}",
                "Content-Type": _mime(path),
            },
            content=audio_file.read(),
            timeout=_TIMEOUT,
        )
    if response.status_code >= 400:
        _raise_http("deepgram", response)
    data = response.json()
    try:
        text = data["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError, TypeError) as exc:
        raise SttBadResult("deepgram parse") from exc
    usable = _usable(text)
    if not usable:
        raise SttBadResult("deepgram empty")
    return usable


def _assemblyai(path: Path, *, language_code: str | None) -> str:
    if not settings.assemblyai_api_key:
        raise SttRateLimited("assemblyai missing key")
    headers = {"authorization": settings.assemblyai_api_key}
    with path.open("rb") as audio_file:
        up = httpx.post(
            "https://api.assemblyai.com/v2/upload",
            headers=headers,
            content=audio_file.read(),
            timeout=_TIMEOUT,
        )
    if up.status_code >= 400:
        _raise_http("assemblyai_upload", up)
    upload_url = (up.json() or {}).get("upload_url")
    if not upload_url:
        raise SttBadResult("assemblyai upload_url")
    body: dict = {"audio_url": upload_url}
    lang = _lang(language_code)
    if lang:
        body["language_code"] = lang
    created = httpx.post(
        "https://api.assemblyai.com/v2/transcript",
        headers={**headers, "content-type": "application/json"},
        json=body,
        timeout=_TIMEOUT,
    )
    if created.status_code >= 400:
        _raise_http("assemblyai_create", created)
    tid = (created.json() or {}).get("id")
    if not tid:
        raise SttBadResult("assemblyai id")
    for _ in range(_POLL_MAX):
        got = httpx.get(
            f"https://api.assemblyai.com/v2/transcript/{tid}",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if got.status_code >= 400:
            _raise_http("assemblyai_poll", got)
        payload = got.json() or {}
        status = str(payload.get("status") or "")
        if status == "completed":
            usable = _usable(payload.get("text"))
            if not usable:
                raise SttBadResult("assemblyai empty")
            return usable
        if status == "error":
            raise SttBadResult("assemblyai error")
        time.sleep(_POLL_SEC)
    raise SttRateLimited("assemblyai timeout")


def _speechmatics(path: Path, *, language_code: str | None) -> str:
    import json as _json

    if not settings.speechmatics_api_key:
        raise SttRateLimited("speechmatics missing key")
    lang = _lang(language_code) or "en"
    config = {
        "type": "transcription",
        "transcription_config": {"language": lang, "operating_point": "enhanced"},
    }
    headers = {"Authorization": f"Bearer {settings.speechmatics_api_key}"}
    with path.open("rb") as audio_file:
        created = httpx.post(
            "https://eu1.asr.api.speechmatics.com/v2/jobs",
            headers=headers,
            data={"config": _json.dumps(config)},
            files={"data_file": (path.name, audio_file, _mime(path))},
            timeout=_TIMEOUT,
        )
    if created.status_code >= 400:
        _raise_http("speechmatics_create", created)
    payload = created.json() or {}
    job_id = payload.get("id") or (payload.get("job") or {}).get("id")
    if not job_id:
        raise SttBadResult("speechmatics id")
    for _ in range(_POLL_MAX):
        got = httpx.get(
            f"https://eu1.asr.api.speechmatics.com/v2/jobs/{job_id}/transcript?format=txt",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if got.status_code == 404:
            time.sleep(_POLL_SEC)
            continue
        if got.status_code >= 400:
            status = httpx.get(
                f"https://eu1.asr.api.speechmatics.com/v2/jobs/{job_id}",
                headers=headers,
                timeout=_TIMEOUT,
            )
            if status.status_code < 400:
                job_status = str(((status.json() or {}).get("job") or {}).get("status") or "")
                if job_status in {"rejected", "failed"}:
                    raise SttBadResult("speechmatics failed")
            if got.status_code in {429, 503}:
                _raise_http("speechmatics_poll", got)
            time.sleep(_POLL_SEC)
            continue
        usable = _usable(got.text)
        if not usable:
            raise SttBadResult("speechmatics empty")
        return usable
    raise SttRateLimited("speechmatics timeout")


def _gladia(path: Path, *, language_code: str | None) -> str:
    if not settings.gladia_api_key:
        raise SttRateLimited("gladia missing key")
    headers = {"x-gladia-key": settings.gladia_api_key}
    with path.open("rb") as audio_file:
        up = httpx.post(
            "https://api.gladia.io/v2/upload",
            headers=headers,
            files={"audio": (path.name, audio_file, _mime(path))},
            timeout=_TIMEOUT,
        )
    if up.status_code >= 400:
        _raise_http("gladia_upload", up)
    audio_url = (up.json() or {}).get("audio_url")
    if not audio_url:
        raise SttBadResult("gladia audio_url")
    body: dict = {"audio_url": audio_url}
    lang = _lang(language_code)
    if lang:
        body["language_config"] = {"languages": [lang]}
    created = httpx.post(
        "https://api.gladia.io/v2/pre-recorded",
        headers={**headers, "Content-Type": "application/json"},
        json=body,
        timeout=_TIMEOUT,
    )
    if created.status_code >= 400:
        _raise_http("gladia_create", created)
    payload = created.json() or {}
    result_url = payload.get("result_url") or (
        f"https://api.gladia.io/v2/pre-recorded/{payload.get('id')}" if payload.get("id") else None
    )
    if not result_url:
        raise SttBadResult("gladia result_url")
    for _ in range(_POLL_MAX):
        got = httpx.get(result_url, headers=headers, timeout=_TIMEOUT)
        if got.status_code >= 400:
            _raise_http("gladia_poll", got)
        data = got.json() or {}
        status = str(data.get("status") or "")
        if status == "done":
            result = data.get("result") or {}
            transcription = result.get("transcription") or {}
            text = transcription.get("full_transcript") or transcription.get("text")
            usable = _usable(text)
            if not usable:
                raise SttBadResult("gladia empty")
            return usable
        if status in {"error", "failed"}:
            raise SttBadResult("gladia error")
        time.sleep(_POLL_SEC)
    raise SttRateLimited("gladia timeout")


def _elevenlabs(path: Path, *, api_key: str, label: str, language_code: str | None) -> str:
    if not api_key:
        raise SttRateLimited(f"{label} missing key")
    with path.open("rb") as audio_file:
        response = httpx.post(
            "https://api.elevenlabs.io/v1/speech-to-text",
            headers={"xi-api-key": api_key},
            data={"model_id": "scribe_v2"},
            files={"file": (path.name, audio_file, _mime(path))},
            timeout=_TIMEOUT,
        )
    if response.status_code >= 400:
        _raise_http(label, response)
    text = (response.json() or {}).get("text")
    usable = _usable(text)
    if not usable:
        raise SttBadResult(f"{label} empty")
    return usable


def _soniox(path: Path, *, language_code: str | None) -> str:
    if not settings.soniox_api_key:
        raise SttRateLimited("soniox missing key")
    headers = {"Authorization": f"Bearer {settings.soniox_api_key}"}
    with path.open("rb") as audio_file:
        up = httpx.post(
            "https://api.soniox.com/v1/files",
            headers=headers,
            files={"file": (path.name, audio_file, _mime(path))},
            timeout=_TIMEOUT,
        )
    if up.status_code >= 400:
        _raise_http("soniox_upload", up)
    file_id = (up.json() or {}).get("id")
    if not file_id:
        raise SttBadResult("soniox file_id")
    body: dict = {"model": "stt-async-v5", "file_id": file_id}
    lang = _lang(language_code)
    if lang:
        body["language_hints"] = [lang]
    created = httpx.post(
        "https://api.soniox.com/v1/transcriptions",
        headers={**headers, "Content-Type": "application/json"},
        json=body,
        timeout=_TIMEOUT,
    )
    if created.status_code >= 400:
        _raise_http("soniox_create", created)
    tid = (created.json() or {}).get("id")
    if not tid:
        raise SttBadResult("soniox id")
    for _ in range(_POLL_MAX):
        got = httpx.get(
            f"https://api.soniox.com/v1/transcriptions/{tid}",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if got.status_code >= 400:
            _raise_http("soniox_poll", got)
        payload = got.json() or {}
        status = str(payload.get("status") or "")
        if status == "completed":
            tr = httpx.get(
                f"https://api.soniox.com/v1/transcriptions/{tid}/transcript",
                headers=headers,
                timeout=_TIMEOUT,
            )
            if tr.status_code >= 400:
                _raise_http("soniox_transcript", tr)
            data = tr.json() if tr.headers.get("content-type", "").startswith("application/json") else {}
            text = (data or {}).get("text") if isinstance(data, dict) else tr.text
            usable = _usable(text if isinstance(text, str) else None)
            if not usable:
                raise SttBadResult("soniox empty")
            return usable
        if status in {"failed", "error"}:
            raise SttBadResult("soniox failed")
        time.sleep(_POLL_SEC)
    raise SttRateLimited("soniox timeout")


def _openai(path: Path, *, duration_seconds: float | None, language_code: str | None) -> str:
    if not settings.openai_api_key:
        raise ExtractError("OPENAI_API_KEY is not configured")
    client = OpenAI(api_key=settings.openai_api_key)
    with path.open("rb") as audio_file:
        kwargs: dict = {
            "model": settings.transcribe_model,
            "file": audio_file,
            "response_format": "json",
        }
        lang = _lang(language_code)
        if lang:
            kwargs["language"] = lang
        result = client.audio.transcriptions.create(**kwargs)
    record_transcription_usage(
        result,
        duration_seconds=duration_seconds,
        fallback_cents=estimate_miss_cost_cents(
            duration_seconds=int(duration_seconds) if duration_seconds else None,
            used_transcribe=True,
        )
        - settings.cost_text_cents_per_extract,
    )
    text = _usable(getattr(result, "text", None) or str(result))
    if not text:
        raise SttBadResult("openai empty")
    return text


def rotate_transcript(
    audio_path: Path,
    *,
    duration_seconds: float | None = None,
    language_code: str | None = None,
    local_fn: Callable[[Path], str | None] | None = None,
    is_good: Callable[[str], bool] | None = None,
) -> tuple[str, str]:
    """Try remote STT providers in round-robin order.

    Returns (text, provider_name).
    After remotes fail: local if concurrent jobs < stt_local_max_active_jobs, else OpenAI.
    """
    providers: list[tuple[str, Callable[[], str]]] = []
    if settings.groq_api_key:
        providers.append(("groq", lambda: _groq(audio_path, language_code=language_code)))
    if settings.deepgram_api_key:
        providers.append(("deepgram", lambda: _deepgram(audio_path, language_code=language_code)))
    if settings.assemblyai_api_key:
        providers.append(("assemblyai", lambda: _assemblyai(audio_path, language_code=language_code)))
    if settings.speechmatics_api_key:
        providers.append(("speechmatics", lambda: _speechmatics(audio_path, language_code=language_code)))
    if settings.gladia_api_key:
        providers.append(("gladia", lambda: _gladia(audio_path, language_code=language_code)))
    if settings.elevenlabs_api_key:
        providers.append(
            (
                "elevenlabs_1",
                lambda: _elevenlabs(
                    audio_path,
                    api_key=settings.elevenlabs_api_key,
                    label="elevenlabs_1",
                    language_code=language_code,
                ),
            )
        )
    if settings.elevenlabs_api_key_2:
        providers.append(
            (
                "elevenlabs_2",
                lambda: _elevenlabs(
                    audio_path,
                    api_key=settings.elevenlabs_api_key_2,
                    label="elevenlabs_2",
                    language_code=language_code,
                ),
            )
        )
    if settings.soniox_api_key:
        providers.append(("soniox", lambda: _soniox(audio_path, language_code=language_code)))

    def _accept(name: str, text: str) -> str:
        if is_good is not None and not is_good(text):
            raise SttBadResult(f"{name} rejected_by_quality")
        return text

    global _rr_index
    start = 0
    if providers:
        with _rr_lock:
            start = _rr_index % len(providers)
            _rr_index += 1

    for offset in range(len(providers)):
        name, fn = providers[(start + offset) % len(providers)]
        try:
            text = _accept(name, fn())
            logger.info("extract stage=stt_ok provider=%s chars=%d", name, len(text))
            return text, name
        except SttRateLimited as exc:
            logger.warning("extract stage=stt_skip provider=%s reason=rate_or_auth detail=%s", name, exc)
        except SttBadResult as exc:
            logger.warning("extract stage=stt_skip provider=%s reason=bad_result detail=%s", name, exc)
        except Exception as exc:
            logger.warning(
                "extract stage=stt_skip provider=%s reason=error error_type=%s",
                name,
                type(exc).__name__,
            )

    active, _ = active_counts()
    if active < settings.stt_local_max_active_jobs and local_fn is not None:
        local_text = local_fn(audio_path)
        usable = _usable(local_text)
        if usable:
            try:
                text = _accept("local", usable)
                logger.info("extract stage=stt_ok provider=local chars=%d active=%d", len(text), active)
                return text, "local"
            except SttBadResult:
                logger.warning("extract stage=stt_skip provider=local reason=bad_result active=%d", active)
        else:
            logger.warning("extract stage=stt_skip provider=local reason=bad_or_empty active=%d", active)

    text = _accept(
        "openai",
        _openai(audio_path, duration_seconds=duration_seconds, language_code=language_code),
    )
    logger.info("extract stage=stt_ok provider=openai chars=%d active=%d", len(text), active)
    return text, "openai"
