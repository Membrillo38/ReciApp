from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request

from app.config import settings
from app.security import safe_urlopen, safe_urlopen_limited, validate_public_url

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
    media_id: str | None = None
    play_urls: list[str] | None = None


@dataclass
class VideoFrames:
    paths: list[Path]
    directory: Path


MAX_VIDEO_BYTES = 50_000_000
MAX_VIDEO_FRAMES = 32
MIN_OVERLAY_INTERVAL_SECONDS = 1.5
MAX_FRAME_BYTES = 2_000_000
VIDEO_DOWNLOAD_TIMEOUT_SECONDS = 120
FRAME_EXTRACT_TIMEOUT_SECONDS = 180
VIDEO_PROBE_TIMEOUT_SECONDS = 10
VISION_FPS = 5.0
DHASH_HAMMING_THRESHOLD = 6
MAX_UNIQUE_VISION_FRAMES = 48
COVER_WINDOW_SECONDS = 2.0
COVER_FRAME_COUNT = 8
COVER_GRAY_SIZE = 64
COVER_DOWNLOAD_SECTION = "*0-2.2"
_VIDEO_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


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
        fallback = _metadata_fallback(url)
        if fallback:
            return _with_tiktok_page_evidence(url, fallback)
        raise
    if meta.returncode != 0:
        err = (meta.stderr or meta.stdout or "unknown yt-dlp error").strip()
        fallback = _metadata_fallback(url)
        if fallback:
            return _with_tiktok_page_evidence(url, fallback)
        raise ExtractError(err[-500:])

    try:
        data = _parse_json(meta.stdout)
    except ExtractError:
        fallback = _metadata_fallback(url)
        if fallback:
            return _with_tiktok_page_evidence(url, fallback)
        raise
    duration = data.get("duration")
    if isinstance(duration, (int, float)) and duration > settings.max_duration_seconds:
        raise ExtractError(
            f"Video too long ({int(duration)}s). Max {settings.max_duration_seconds}s."
        )

    media = _with_tiktok_page_evidence(
        url,
        MediaInfo(
            title=(data.get("title") or "").strip(),
            description=(data.get("description") or "").strip(),
            author=_author_from_info(data),
            thumbnail_url=_thumbnail_from_info(data),
            duration_seconds=int(duration) if isinstance(duration, (int, float)) else None,
            webpage_url=data.get("webpage_url") or url,
            subtitles_text=_extract_subtitles_from_info(data),
            audio_path=None,
            media_id=str(data.get("id") or "video"),
        ),
    )
    return media


def download_audio(url: str, media_id: str | None = None) -> Path | None:
    """Lazy audio download for STT stages only."""
    try:
        validate_public_url(url, allowed_hosts=_SOURCE_HOSTS)
    except ValueError as exc:
        raise ExtractError(str(exc)) from exc
    return _download_audio(url, media_id or "audio")


def _host_matches(url: str, *roots: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(host == root or host.endswith(f".{root}") for root in roots)


def overlay_frame_interval(duration: float, max_frames: int = MAX_VIDEO_FRAMES) -> float:
    """Space overlay samples tightly enough to catch short ingredient cards."""
    frames = max(1, min(int(max_frames), MAX_VIDEO_FRAMES))
    return max(MIN_OVERLAY_INTERVAL_SECONDS, max(float(duration), 1.0) / frames)


def overlay_sample_times(duration: float, max_frames: int = MAX_VIDEO_FRAMES) -> list[float]:
    """Return ordered timestamps covering sequential on-screen ingredient cards."""
    duration = max(float(duration), 1.0)
    interval = overlay_frame_interval(duration, max_frames)
    start = min(1.2, max(duration * 0.08, 0.2))
    times: list[float] = []
    t = start
    while len(times) < max_frames and t < duration - 0.12:
        times.append(round(t, 3))
        t += interval
    last = round(max(duration - 0.35, 0.0), 3)
    if not times:
        return [min(last, duration / 2)]
    if abs(times[-1] - last) > interval * 0.45:
        if len(times) < max_frames:
            times.append(last)
        else:
            times[-1] = last
    out: list[float] = []
    for stamp in times:
        clipped = min(max(stamp, 0.0), max(duration - 0.05, 0.0))
        if not out or abs(out[-1] - clipped) > 0.2:
            out.append(clipped)
    return out


def _with_tiktok_page_evidence(url: str, media: MediaInfo) -> MediaInfo:
    """Fill spoken captions and play URLs from TikTok page hydration."""
    if not _host_matches(url, "tiktok.com"):
        return media
    try:
        from app.tiktok_slides import fetch_tiktok_item, tiktok_caption_urls, tiktok_play_urls

        item = fetch_tiktok_item(url)
    except Exception:
        return media
    if not item or item.get("imagePost") or item.get("image_post"):
        return media
    captions = None
    for caption_url in tiktok_caption_urls(item)[:4]:
        captions = _download_subtitle_url(caption_url)
        if captions:
            break
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    duration = media.duration_seconds
    raw_duration = video.get("duration") if isinstance(video, dict) else None
    if duration is None and isinstance(raw_duration, (int, float)) and raw_duration > 0:
        duration = int(raw_duration)
    desc = str(item.get("desc") or "").strip()
    author = media.author
    raw_author = item.get("author")
    if not author and isinstance(raw_author, dict):
        author = str(raw_author.get("uniqueId") or "").strip() or None
    subtitles = media.subtitles_text
    if captions and len(captions) > len(subtitles or ""):
        subtitles = captions
    play_urls = list(media.play_urls or []) or tiktok_play_urls(item)
    return replace(
        media,
        title=media.title or desc,
        description=media.description or desc,
        author=author,
        duration_seconds=duration,
        subtitles_text=subtitles,
        play_urls=play_urls or None,
    )


def _metadata_fallback(url: str) -> MediaInfo | None:
    return _fetch_tiktok_oembed(url) or _fetch_instagram_oembed(url) or _fetch_youtube_oembed(url)


def _oembed_json(endpoint: str) -> dict | None:
    try:
        request = Request(endpoint, headers={"User-Agent": "Mozilla/5.0 recipe-extractor/1.0"})
        raw = safe_urlopen_limited(request, timeout=20, max_bytes=1_000_000)
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _media_from_oembed(url: str, data: dict | None) -> MediaInfo | None:
    if not data:
        return None
    title = str(data.get("title") or "").strip()
    if not title:
        return None
    caption = title[:12_000]
    return MediaInfo(
        title=caption,
        description=caption,
        author=str(data.get("author_name") or "").strip() or None,
        thumbnail_url=str(data.get("thumbnail_url") or "").strip() or None,
        duration_seconds=None,
        webpage_url=url,
        subtitles_text=None,
        audio_path=None,
        media_id=None,
    )


def _canonical_instagram_url(url: str) -> str:
    parts = [part for part in (urlparse(url).path or "").split("/") if part]
    if len(parts) >= 2 and parts[0].lower() in {"reel", "p", "tv"}:
        return f"https://www.instagram.com/{parts[0].lower()}/{parts[1]}/"
    return url


def _fetch_tiktok_oembed(url: str) -> MediaInfo | None:
    """Use TikTok's public metadata endpoint when yt-dlp cannot extract a video."""
    if not _host_matches(url, "tiktok.com"):
        return None
    return _media_from_oembed(url, _oembed_json(f"https://www.tiktok.com/oembed?url={quote(url, safe='')}"))


def _fetch_instagram_oembed(url: str) -> MediaInfo | None:
    """Use Instagram's public oEmbed caption when yt-dlp is login-walled."""
    if not _host_matches(url, "instagram.com"):
        return None
    target = _canonical_instagram_url(url)
    return _media_from_oembed(url, _oembed_json(f"https://www.instagram.com/api/v1/oembed/?url={quote(target, safe='')}"))


def _fetch_youtube_oembed(url: str) -> MediaInfo | None:
    if not _host_matches(url, "youtube.com", "youtu.be"):
        return None
    return _media_from_oembed(
        url,
        _oembed_json(f"https://www.youtube.com/oembed?url={quote(url, safe='')}&format=json"),
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
        raw = safe_urlopen_limited(req, timeout=20, max_bytes=2_000_000)
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


def _http_download_video(play_url: str, output: Path) -> None:
    validate_public_url(play_url)
    request = Request(
        play_url,
        headers={"User-Agent": _VIDEO_UA, "Referer": "https://www.tiktok.com/"},
    )
    with safe_urlopen(request, timeout=VIDEO_DOWNLOAD_TIMEOUT_SECONDS) as response:
        written = 0
        with output.open("wb") as handle:
            while True:
                chunk = response.read(65_536)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_VIDEO_BYTES:
                    raise ExtractError("TikTok video frame fallback exceeded the download bound")
                handle.write(chunk)
    if written <= 0:
        raise ExtractError("TikTok video frame fallback download failed")


def _download_tiktok_media(url: str, output: Path, play_urls: list[str] | None) -> None:
    try:
        proc = _run_ytdlp(
            [
                "--format",
                "best[ext=mp4]/best",
                "--max-filesize",
                "50M",
                "--socket-timeout",
                "20",
                "--retries",
                "2",
                "--no-playlist",
                "--no-warnings",
                "-o",
                str(output),
                url,
            ],
            timeout=VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
        )
        if proc.returncode == 0 and output.is_file() and 0 < output.stat().st_size <= MAX_VIDEO_BYTES:
            return
    except ExtractError:
        pass
    output.unlink(missing_ok=True)
    last_error: Exception | None = None
    for play_url in (play_urls or [])[:3]:
        try:
            _http_download_video(play_url, output)
            if output.is_file() and 0 < output.stat().st_size <= MAX_VIDEO_BYTES:
                return
        except Exception as exc:
            last_error = exc
            output.unlink(missing_ok=True)
    raise ExtractError("TikTok video frame fallback download failed") from last_error


def download_tiktok_video_frames(
    url: str,
    *,
    media_id: str | None,
    duration_seconds: int | None,
    play_urls: list[str] | None = None,
) -> VideoFrames:
    """Backward-compatible TikTok entry point for bounded vision frames."""
    return download_video_frames(
        url,
        media_id=media_id,
        duration_seconds=duration_seconds,
        play_urls=play_urls,
        allowed_hosts={"tiktok.com"},
    )


def download_video_frames(
    url: str,
    *,
    media_id: str | None,
    duration_seconds: int | None,
    play_urls: list[str] | None = None,
    allowed_hosts: set[str] | None = None,
    max_unique_frames: int = MAX_UNIQUE_VISION_FRAMES,
) -> VideoFrames:
    """Download media, sample at 5 FPS, drop near-duplicate frames via dHash."""
    hosts = allowed_hosts or _SOURCE_HOSTS
    try:
        validate_public_url(url, allowed_hosts=hosts)
    except ValueError as exc:
        raise ExtractError(str(exc)) from exc
    if duration_seconds is not None and duration_seconds > settings.max_duration_seconds:
        raise ExtractError(
            f"Video too long ({duration_seconds}s). Max {settings.max_duration_seconds}s."
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="recipe-video-frames-"))
    safe_media_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(media_id or "video"))[:100] or "video"
    output = tmpdir / f"{safe_media_id}.mp4"
    try:
        _download_video_media(url, output, play_urls)
        if not output.is_file() or output.stat().st_size <= 0 or output.stat().st_size > MAX_VIDEO_BYTES:
            raise ExtractError("Video frame download exceeded the download bound")
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise ExtractError("ffmpeg and ffprobe are required on the extraction server")

        try:
            probe = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(output),
                ],
                capture_output=True,
                text=True,
                timeout=VIDEO_PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ExtractError("Video duration probe timed out") from exc
        try:
            duration = float((probe.stdout or "").strip())
        except ValueError as exc:
            raise ExtractError("Video duration could not be verified") from exc
        if probe.returncode != 0 or duration <= 0:
            raise ExtractError("Video duration could not be verified")
        if duration > settings.max_duration_seconds:
            raise ExtractError(
                f"Video too long ({int(duration)}s). Max {settings.max_duration_seconds}s."
            )
        duration = max(1.0, duration)
        unique_times = _unique_frame_times(output, duration, ffmpeg=ffmpeg)
        if not unique_times:
            raise ExtractError("Video frame 1 could not be sampled")
        capped = unique_times[: max(1, min(int(max_unique_frames), MAX_UNIQUE_VISION_FRAMES))]
        paths = _extract_jpeg_at_times(output, capped, tmpdir, ffmpeg=ffmpeg)
        if not paths:
            raise ExtractError("Video frame 1 could not be sampled")
        for index, frame_path in enumerate(paths, start=1):
            size = frame_path.stat().st_size
            if size <= 0 or size > MAX_FRAME_BYTES:
                raise ExtractError(f"Video frame {index} exceeded the size bound")
        output.unlink(missing_ok=True)
        return VideoFrames(paths=paths, directory=tmpdir)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def _download_video_media(url: str, output: Path, play_urls: list[str] | None) -> None:
    if _host_matches(url, "tiktok.com"):
        _download_tiktok_media(url, output, play_urls)
        return
    try:
        proc = _run_ytdlp(
            [
                "--format",
                "best[ext=mp4]/best",
                "--max-filesize",
                "50M",
                "--socket-timeout",
                "20",
                "--retries",
                "2",
                "--no-playlist",
                "--no-warnings",
                "-o",
                str(output),
                url,
            ],
            timeout=VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
        )
    except ExtractError:
        output.unlink(missing_ok=True)
        raise
    if proc.returncode != 0 or not output.is_file() or output.stat().st_size <= 0:
        output.unlink(missing_ok=True)
        raise ExtractError("Video frame download failed")
    if output.stat().st_size > MAX_VIDEO_BYTES:
        output.unlink(missing_ok=True)
        raise ExtractError("Video frame download exceeded the download bound")


def _unique_frame_times(video_path: Path, duration: float, *, ffmpeg: str) -> list[float]:
    """Sample 5 FPS tiny greyscale thumbs and keep timestamps that differ by dHash."""
    thumb_file = video_path.parent / "thumbs.raw"
    try:
        thumb = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vf",
                f"fps={VISION_FPS:.4f},scale=9:8:flags=fast_bilinear,format=gray",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                "-y",
                str(thumb_file),
            ],
            capture_output=True,
            timeout=FRAME_EXTRACT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractError("Video frame extraction timed out") from exc
    if thumb.returncode != 0 or not thumb_file.is_file():
        return overlay_sample_times(duration, max_frames=MAX_VIDEO_FRAMES)

    try:
        blob = thumb_file.read_bytes()
    finally:
        thumb_file.unlink(missing_ok=True)
    frame_size = 72
    if len(blob) < frame_size:
        return overlay_sample_times(duration, max_frames=MAX_VIDEO_FRAMES)

    unique_times: list[float] = []
    last_hash: int | None = None
    total = len(blob) // frame_size
    for index in range(total):
        pixels = blob[index * frame_size : (index + 1) * frame_size]
        digest = _dhash64(pixels)
        stamp = round(min(index / VISION_FPS, max(duration - 0.05, 0.0)), 3)
        if last_hash is None or _hamming64(last_hash, digest) > DHASH_HAMMING_THRESHOLD:
            unique_times.append(stamp)
            last_hash = digest
    return unique_times


def _extract_jpeg_at_times(
    video_path: Path,
    times: list[float],
    tmpdir: Path,
    *,
    ffmpeg: str,
) -> list[Path]:
    paths: list[Path] = []
    for index, stamp in enumerate(times, start=1):
        out = tmpdir / f"frame-{index:03d}.jpg"
        try:
            frame = subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{stamp:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=720:720:force_original_aspect_ratio=decrease",
                    "-q:v",
                    "4",
                    "-y",
                    str(out),
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired:
            continue
        if frame.returncode == 0 and out.is_file() and out.stat().st_size > 0:
            paths.append(out)
        else:
            out.unlink(missing_ok=True)
    return paths


def _dhash64(pixels: bytes) -> int:
    """Difference hash over a 9x8 greyscale buffer."""
    value = 0
    bit = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            left = pixels[base + col]
            right = pixels[base + col + 1]
            if left > right:
                value |= 1 << bit
            bit += 1
    return value


def _hamming64(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def cover_sample_times(duration: float) -> list[float]:
    """Eight timestamps in the first two seconds (or the whole clip if shorter)."""
    window = min(COVER_WINDOW_SECONDS, max(float(duration), 0.04))
    return [
        round((index + 0.5) * window / COVER_FRAME_COUNT, 3)
        for index in range(COVER_FRAME_COUNT)
    ]


def download_cover_frames(
    url: str,
    *,
    media_id: str | None,
    duration_seconds: int | None,
    play_urls: list[str] | None = None,
) -> VideoFrames:
    """Download a short prefix and extract eight JPEGs for cover selection."""
    try:
        validate_public_url(url, allowed_hosts=_SOURCE_HOSTS)
    except ValueError as exc:
        raise ExtractError(str(exc)) from exc
    if duration_seconds is not None and duration_seconds > settings.max_duration_seconds:
        raise ExtractError(
            f"Video too long ({duration_seconds}s). Max {settings.max_duration_seconds}s."
        )

    tmpdir = Path(tempfile.mkdtemp(prefix="recipe-cover-frames-"))
    safe_media_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(media_id or "video"))[:100] or "video"
    output = tmpdir / f"{safe_media_id}.mp4"
    try:
        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if not ffmpeg or not ffprobe:
            raise ExtractError("ffmpeg and ffprobe are required on the extraction server")
        _download_cover_media(url, output, play_urls)
        if not output.is_file() or output.stat().st_size <= 0 or output.stat().st_size > MAX_VIDEO_BYTES:
            raise ExtractError("Video frame download exceeded the download bound")
        duration = _probe_duration(output, ffprobe=ffprobe)
        window = min(COVER_WINDOW_SECONDS, duration)
        fps = COVER_FRAME_COUNT / window
        gray_path = tmpdir / "cover.raw"
        _run_ffmpeg_cover(
            ffmpeg,
            output,
            window,
            vf=f"fps={fps:.4f},scale={COVER_GRAY_SIZE}:{COVER_GRAY_SIZE}:flags=fast_bilinear,format=gray",
            extra=["-f", "rawvideo", "-pix_fmt", "gray"],
            dest=gray_path,
        )
        pattern = tmpdir / "cover-%02d.jpg"
        _run_ffmpeg_cover(
            ffmpeg,
            output,
            window,
            vf=f"fps={fps:.4f},scale=720:720:force_original_aspect_ratio=decrease",
            extra=["-q:v", "4"],
            dest=pattern,
        )
        paths = sorted(path for path in tmpdir.glob("cover-*.jpg") if path.is_file())[:COVER_FRAME_COUNT]
        if not paths:
            raise ExtractError("Video frame 1 could not be sampled")
        for index, frame_path in enumerate(paths, start=1):
            size = frame_path.stat().st_size
            if size <= 0 or size > MAX_FRAME_BYTES:
                raise ExtractError(f"Video frame {index} exceeded the size bound")
        output.unlink(missing_ok=True)
        return VideoFrames(paths=paths, directory=tmpdir)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise


def select_best_cover_path(paths: list[Path], directory: Path | None = None) -> Path | None:
    """Pick the sharpest well-lit frame; file size is the fallback."""
    usable = [path for path in paths if path.is_file() and path.stat().st_size > 0]
    if not usable:
        return None
    gray_path = (directory or usable[0].parent) / "cover.raw"
    frame = COVER_GRAY_SIZE * COVER_GRAY_SIZE
    blob = gray_path.read_bytes() if gray_path.is_file() else b""
    count = min(len(usable), len(blob) // frame) if blob else 0
    if count:
        scores = [
            _gray_cover_score(blob[index * frame : (index + 1) * frame])
            for index in range(count)
        ]
        return usable[max(range(len(scores)), key=lambda index: scores[index])]
    return max(usable, key=lambda path: path.stat().st_size)


def _gray_cover_score(pixels: bytes) -> float:
    n = len(pixels)
    if n == 0:
        return 0.0
    mean = sum(pixels) / n
    variance = sum((pixel - mean) ** 2 for pixel in pixels) / n
    if mean < 18 or mean > 238:
        return variance * 0.05
    return variance


def _probe_duration(video_path: Path, *, ffprobe: str) -> float:
    try:
        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=VIDEO_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractError("Video duration probe timed out") from exc
    try:
        duration = float((probe.stdout or "").strip())
    except ValueError as exc:
        raise ExtractError("Video duration could not be verified") from exc
    if probe.returncode != 0 or duration <= 0:
        raise ExtractError("Video duration could not be verified")
    if duration > settings.max_duration_seconds:
        raise ExtractError(
            f"Video too long ({int(duration)}s). Max {settings.max_duration_seconds}s."
        )
    return max(duration, 0.04)


def _run_ffmpeg_cover(
    ffmpeg: str,
    video_path: Path,
    window: float,
    *,
    vf: str,
    extra: list[str],
    dest: Path,
) -> None:
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-ss",
                "0",
                "-t",
                f"{window:.3f}",
                "-i",
                str(video_path),
                "-vf",
                vf,
                *extra,
                "-y",
                str(dest),
            ],
            capture_output=True,
            timeout=FRAME_EXTRACT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExtractError("Video frame extraction timed out") from exc
    if result.returncode != 0 and dest.is_file():
        dest.unlink(missing_ok=True)


def _download_cover_media(url: str, output: Path, play_urls: list[str] | None) -> None:
    extra = ["--download-sections", COVER_DOWNLOAD_SECTION, "--force-keyframes-at-cuts"]
    try:
        proc = _run_ytdlp(
            [
                "--format",
                "best[ext=mp4]/best",
                "--max-filesize",
                "50M",
                "--socket-timeout",
                "20",
                "--retries",
                "2",
                "--no-playlist",
                "--no-warnings",
                *extra,
                "-o",
                str(output),
                url,
            ],
            timeout=VIDEO_DOWNLOAD_TIMEOUT_SECONDS,
        )
        if proc.returncode == 0 and output.is_file() and 0 < output.stat().st_size <= MAX_VIDEO_BYTES:
            return
    except ExtractError:
        pass
    output.unlink(missing_ok=True)
    _download_video_media(url, output, play_urls)


def select_spread_frame_indexes(total: int, limit: int) -> list[int]:
    """Pick up to `limit` indexes spread across the sequence."""
    if total <= 0 or limit <= 0:
        return []
    if total <= limit:
        return list(range(total))
    if limit == 1:
        return [0]
    step = (total - 1) / (limit - 1)
    picks: list[int] = []
    for i in range(limit):
        index = int(round(i * step))
        if not picks or picks[-1] != index:
            picks.append(index)
    while len(picks) < limit:
        for index in range(total):
            if index not in picks:
                picks.append(index)
                break
        else:
            break
    return sorted(picks)[:limit]
