from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request

from app.config import settings
from app.security import safe_urlopen, validate_public_url

_SOURCE_HOSTS = {
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
}


class ExtractError(Exception):
    pass


@dataclass
class MediaInfo:
    title: str
    description: str
    author: str | None
    thumbnail_url: str | None
    duration_seconds: int | None
    webpage_url: str
    subtitles_text: str | None
    audio_path: Path | None
    extra_text: str | None = None


def _run_ytdlp(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [sys.executable, "-m", "yt_dlp", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ExtractError("yt-dlp is not installed on the extraction server") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExtractError(f"yt-dlp timed out after {timeout}s") from exc


def _parse_json(stdout: str) -> dict:
    if not stdout.strip():
        raise ExtractError("yt-dlp returned empty output")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExtractError("yt-dlp returned invalid JSON") from exc


def fetch_media_info(url: str) -> MediaInfo:
    try:
        validate_public_url(url, allowed_hosts=_SOURCE_HOSTS)
    except ValueError as exc:
        raise ExtractError(str(exc)) from exc
    try:
        meta = _run_ytdlp(
            [
                "--dump-single-json",
                "--no-playlist",
                "--no-warnings",
                "--max-filesize",
                "50M",
                "--socket-timeout",
                "20",
                "--retries",
                "2",
                url,
            ],
            timeout=90,
        )
    except ExtractError:
        fallback = _fetch_tiktok_oembed(url)
        if fallback:
            return fallback
        raise
    if meta.returncode != 0:
        err = (meta.stderr or meta.stdout or "unknown yt-dlp error").strip()
        fallback = _fetch_tiktok_oembed(url)
        if fallback:
            return fallback
        raise ExtractError(err[-500:])

    try:
        data = _parse_json(meta.stdout)
    except ExtractError:
        fallback = _fetch_tiktok_oembed(url)
        if fallback:
            return fallback
        raise
    duration = data.get("duration")
    if isinstance(duration, (int, float)) and duration > settings.max_duration_seconds:
        raise ExtractError(
            f"Video too long ({int(duration)}s). Max {settings.max_duration_seconds}s."
        )

    subtitles_text = _extract_subtitles_from_info(data)
    audio_path = None
    if not subtitles_text:
        try:
            audio_path = _download_audio(url, data.get("id") or "audio")
        except ExtractError:
            # Metadata can still yield a valid recipe when media download or
            # post-processing is temporarily unavailable.
            audio_path = None

    return MediaInfo(
        title=(data.get("title") or "").strip(),
        description=(data.get("description") or "").strip(),
        author=_author_from_info(data),
        thumbnail_url=_thumbnail_from_info(data),
        duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
        webpage_url=data.get("webpage_url") or url,
        subtitles_text=subtitles_text,
        audio_path=audio_path,
    )


def _fetch_tiktok_oembed(url: str) -> MediaInfo | None:
    """Use TikTok's public metadata endpoint when yt-dlp cannot extract a video."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host not in {"tiktok.com", "www.tiktok.com"}:
        return None
    endpoint = f"https://www.tiktok.com/oembed?url={quote(url, safe='')}"
    try:
        request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0 recipe-extractor/1.0"})
        with safe_urlopen(request, timeout=20) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            return None
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("type") != "video":
        return None
    title = str(data.get("title") or "").strip()
    if not title:
        return None
    return MediaInfo(
        title=title[:12_000],
        description="",
        author=str(data.get("author_name") or "").strip() or None,
        thumbnail_url=str(data.get("thumbnail_url") or "").strip() or None,
        duration_seconds=None,
        webpage_url=url,
        subtitles_text=None,
        audio_path=None,
    )


def _author_from_info(data: dict) -> str | None:
    uploader = data.get("uploader") or data.get("channel")
    if uploader:
        return str(uploader)
    creator = data.get("creator")
    return str(creator) if creator else None


def _thumbnail_from_info(data: dict) -> str | None:
    thumb = data.get("thumbnail")
    if thumb:
        return str(thumb)
    thumbs = data.get("thumbnails") or []
    if thumbs:
        return str(thumbs[-1].get("url") or "")
    return None


def _extract_subtitles_from_info(data: dict) -> str | None:
    chunks: list[str] = []

    for key in ("subtitles", "automatic_captions"):
        tracks = data.get(key) or {}
        for lang in ("es", "es-ES", "en", "en-US"):
            entries = tracks.get(lang) or tracks.get(lang.split("-")[0])
            if not entries:
                continue
            for entry in entries:
                if entry.get("ext") in {"vtt", "srv3", "json3"} and entry.get("url"):
                    text = _download_subtitle_url(str(entry["url"]))
                    if text:
                        chunks.append(text)
                        break
            if chunks:
                break
        if chunks:
            break

    merged = "\n".join(chunks).strip()
    return merged or None


def _download_subtitle_url(url: str) -> str | None:
    import re
    import urllib.request

    try:
        validate_public_url(url)
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 recipe-extractor/1.0"},
        )
        with safe_urlopen(req, timeout=20) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            return None
        raw = raw.decode("utf-8", "replace")
    except Exception:
        return None

    lines = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or "-->" in line or line.isdigit():
            continue
        cleaned = re.sub(r"<[^>]+>", "", line).strip()
        if cleaned:
            lines.append(cleaned)
    text = " ".join(lines).strip()
    return text or None


def _download_audio(url: str, media_id: str) -> Path | None:
    tmpdir = Path(tempfile.mkdtemp(prefix="recipe-audio-"))
    safe_media_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(media_id))[:100] or "audio"
    out_template = str(tmpdir / f"{safe_media_id}.%(ext)s")
    try:
        proc = _run_ytdlp(
            [
                "-x",
                "--audio-format",
                "mp3",
                "--audio-quality",
                "5",
                "--max-filesize",
                "50M",
                "--socket-timeout",
                "20",
                "--retries",
                "2",
                "-o",
                out_template,
                "--no-playlist",
                "--no-warnings",
                url,
            ],
            timeout=180,
        )
    except ExtractError:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    if proc.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None

    matches = list(tmpdir.glob(f"{safe_media_id}.*"))
    if not matches:
        matches = list(tmpdir.glob("*"))
    if not matches:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None
    return matches[0]
