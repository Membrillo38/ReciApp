from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import settings


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
    return subprocess.run(
        ["yt-dlp", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _parse_json(stdout: str) -> dict:
    if not stdout.strip():
        raise ExtractError("yt-dlp returned empty output")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ExtractError("yt-dlp returned invalid JSON") from exc


def fetch_media_info(url: str) -> MediaInfo:
    meta = _run_ytdlp(
        [
            "--dump-single-json",
            "--no-playlist",
            "--no-warnings",
            url,
        ],
        timeout=90,
    )
    if meta.returncode != 0:
        err = (meta.stderr or meta.stdout or "unknown yt-dlp error").strip()
        raise ExtractError(err[-500:])

    data = _parse_json(meta.stdout)
    duration = data.get("duration")
    if isinstance(duration, (int, float)) and duration > settings.max_duration_seconds:
        raise ExtractError(
            f"Video too long ({int(duration)}s). Max {settings.max_duration_seconds}s."
        )

    subtitles_text = _extract_subtitles_from_info(data)
    audio_path = None
    if not subtitles_text:
        audio_path = _download_audio(url, data.get("id") or "audio")

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
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 recipe-extractor/1.0"},
        )
        raw = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
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
    out_template = str(tmpdir / f"{media_id}.%(ext)s")
    proc = _run_ytdlp(
        [
            "-x",
            "--audio-format",
            "mp3",
            "--audio-quality",
            "5",
            "-o",
            out_template,
            "--no-playlist",
            "--no-warnings",
            url,
        ],
        timeout=180,
    )
    if proc.returncode != 0:
        return None

    matches = list(tmpdir.glob(f"{media_id}.*"))
    if not matches:
        matches = list(tmpdir.glob("*"))
    return matches[0] if matches else None
