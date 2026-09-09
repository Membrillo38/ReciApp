from __future__ import annotations

import base64
import html as html_lib
import json
import re
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from app.extract import ExtractError
from app.security import safe_urlopen, validate_public_url

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 "
    "Mobile/15E148 Safari/604.1"
)
MAX_CAROUSEL_SLIDES = 12


@dataclass
class SlideInfo:
    title: str
    description: str
    author: str | None
    image_urls: list[str]
    ocr_text: str | None = None
    total_image_count: int = 0
    incomplete_reason: str | None = None


def fetch_tiktok_slides(url: str) -> SlideInfo | None:
    is_photo = "/photo/" in (urlparse(url).path or "").lower()
    if not is_photo:
        return None

    # Mobile SSR exposes imagePost reliably and avoids an unnecessary desktop
    # request for the only TikTok URL shape that can contain a carousel.
    mobile_html = _fetch_html(url, user_agent=MOBILE_UA)
    mobile_slide_info = _slide_info_from_html(mobile_html or "")
    if mobile_slide_info:
        return mobile_slide_info

    # TikTok photo pages sometimes omit itemStruct/imagePost while still
    # publishing Open Graph metadata. It may expose one cover or several
    # ordered images; use only public HTTPS media and let the recipe pipeline
    # continue with the available evidence instead of failing the whole job.
    # Desktop SSR can expose metadata even when mobile SSR is unavailable.
    html = _fetch_html(url)
    slide_info = _slide_info_from_html(html or "")
    return slide_info or _photo_meta_fallback(html or mobile_html or "", url)


def _slide_info_from_html(html: str) -> SlideInfo | None:
    item = _item_from_html(html)
    if not item:
        return None
    image_post = item.get("imagePost") or item.get("image_post") or {}
    raw_images = image_post.get("images") if isinstance(image_post, dict) else None
    images, total = _image_urls_with_count(raw_images)
    if not images:
        return None
    return SlideInfo(
        title=(image_post.get("title") or item.get("desc") or "").strip(),
        description=(item.get("desc") or "").strip(),
        author=((item.get("author") or {}).get("uniqueId")),
        image_urls=images,
        total_image_count=total,
        incomplete_reason=(
            f"TikTok carousel has {total} slides; the supported limit is {MAX_CAROUSEL_SLIDES}"
            if total > MAX_CAROUSEL_SLIDES
            else (
                f"TikTok carousel exposes {total} slides but only {len(images)} readable image references"
                if len(images) != total
                else None
            )
        ),
    )


def _image_urls(raw_images: object) -> list[str]:
    """Return stable, bounded slide URLs from TikTok hydration variants."""
    urls, _ = _image_urls_with_count(raw_images)
    return urls


def _image_urls_with_count(raw_images: object) -> tuple[list[str], int]:
    """Return bounded URLs plus the complete readable-reference count."""
    if not isinstance(raw_images, list):
        return [], 0

    output: list[str] = []
    seen: set[str] = set()
    total = len(raw_images)
    for image in raw_images:
        if isinstance(image, str):
            candidates = [image]
        elif isinstance(image, dict):
            image_data = (
                image.get("imageURL")
                or image.get("imageUrl")
                or image.get("image_url")
                or image.get("displayImage")
                or image.get("display_image")
                or {}
            )
            if isinstance(image_data, dict):
                image_data = image_data.get("urlList") or image_data.get("url_list") or image_data
            candidates = image_data
        else:
            continue
        if isinstance(candidates, str):
            candidates = [candidates]
        if not isinstance(candidates, list):
            candidates = []
        # TikTok commonly orders URLs from smaller to larger; try the largest
        # first while retaining original slide order.
        selected: str | None = None
        for value in reversed(candidates):
            candidate = str(value or "").strip()
            parsed = urlparse(candidate)
            if parsed.scheme != "https" or not parsed.netloc:
                continue
            if len(candidate) > 2048 or candidate in seen:
                continue
            selected = candidate
            break
        if selected:
            seen.add(selected)
            if len(output) < MAX_CAROUSEL_SLIDES:
                output.append(selected)
    return output, total


def _photo_meta_fallback(html: str, url: str) -> SlideInfo | None:
    values: dict[str, list[str]] = {}
    for tag in re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE):
        attrs: dict[str, str] = {}
        for match in re.finditer(
            r"([:\w-]+)\s*=\s*[\"'](.*?)[\"']",
            tag,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            attrs[match.group(1)] = match.group(2)
        key = (attrs.get("property") or attrs.get("name") or "").lower()
        content = html_lib.unescape((attrs.get("content") or "").strip())
        if key and content:
            values.setdefault(key, []).append(content)

    images: list[str] = []
    seen: set[str] = set()
    for candidate in values.get("og:image", []) + values.get("twitter:image", []):
        parsed = urlparse(candidate)
        if parsed.scheme != "https" or not parsed.netloc or candidate in seen:
            continue
        seen.add(candidate)
        images.append(candidate)
        if len(images) >= MAX_CAROUSEL_SLIDES:
            break
    if not images:
        return None

    path_parts = [part for part in (urlparse(url).path or "").split("/") if part]
    author = next((part[1:] for part in path_parts if part.startswith("@")), None)
    title = (values.get("og:title") or values.get("twitter:title") or [""])[0]
    description = (values.get("og:description") or values.get("description") or [""])[0]
    return SlideInfo(
        title=title.strip(),
        description=description.strip(),
        author=author,
        image_urls=images,
        total_image_count=len(images),
        incomplete_reason=(
            "TikTok carousel hydration was unavailable; Open Graph images "
            "do not prove complete carousel coverage"
        ),
    )


def _fetch_html(url: str, *, user_agent: str = UA) -> str | None:
    try:
        validate_public_url(url, allowed_hosts={"tiktok.com"})
    except ValueError:
        return None
    for _ in range(2):
        req = urllib.request.Request(url, headers={"User-Agent": user_agent})
        try:
            with safe_urlopen(req, timeout=25) as response:
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                return None
            return raw.decode("utf-8", "replace")
        except Exception:
            continue
    return None


def _item_from_html(html: str) -> dict | None:
    patterns = (
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        r'<script id="SIGI_STATE"[^>]*>(.*?)</script>',
    )
    for pattern in patterns:
        match = re.search(pattern, html, re.S)
        if not match:
            continue
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        item = _dig_item_struct(data)
        if item:
            return item
    return None


def _dig_item_struct(data: dict) -> dict | None:
    try:
        return data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
    except Exception:
        pass

    # SIGI_STATE fallback
    item_module = data.get("ItemModule")
    if isinstance(item_module, dict) and item_module:
        return next(
            (item for item in item_module.values() if isinstance(item, dict)),
            None,
        )

    # Hydration keys have changed over time. Find the nearest item containing
    # TikTok's photo-post payload without assuming one fixed root path.
    def walk(value: object, depth: int = 0) -> dict | None:
        if depth > 8:
            return None
        if isinstance(value, dict):
            image_post = value.get("imagePost") or value.get("image_post")
            if isinstance(image_post, dict) and isinstance(image_post.get("images"), list):
                return value
            for child in value.values():
                found = walk(child, depth + 1)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = walk(child, depth + 1)
                if found:
                    return found
        return None

    return walk(data)


def fetch_tiktok_item(url: str) -> dict | None:
    """Hydrate the public TikTok item payload for videos or photos."""
    html = _fetch_html(url, user_agent=UA)
    item = _item_from_html(html or "")
    if item:
        return item
    html = _fetch_html(url, user_agent=MOBILE_UA)
    return _item_from_html(html or "")


def tiktok_caption_urls(item: dict) -> list[str]:
    """Return HTTPS caption/WebVTT URLs, original language first."""
    video = item.get("video") if isinstance(item, dict) else None
    if not isinstance(video, dict):
        return []
    preferred: list[object] = []
    other: list[object] = []
    cla = video.get("claInfo") or video.get("cla") or {}
    captions = cla.get("captionInfos") if isinstance(cla, dict) else None
    if isinstance(captions, list):
        for cap in captions:
            if not isinstance(cap, dict):
                continue
            target = cap.get("url") or cap.get("Url")
            if cap.get("isOriginalCaption"):
                preferred.append(target)
            else:
                other.append(target)
    for info in video.get("subtitleInfos") or video.get("subtitle_infos") or []:
        if isinstance(info, dict):
            other.append(info.get("Url") or info.get("url"))
    urls: list[str] = []
    seen: set[str] = set()
    for target in preferred + other:
        candidate = str(target or "").strip()
        parsed = urlparse(candidate)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or candidate in seen
            or len(candidate) > 4096
        ):
            continue
        seen.add(candidate)
        urls.append(candidate)
    return urls


def tiktok_play_urls(item: dict) -> list[str]:
    """Return bounded HTTPS media URLs from hydrated play/download addresses."""
    video = item.get("video") if isinstance(item, dict) else None
    if not isinstance(video, dict):
        return []
    urls: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        if len(urls) >= 6:
            return
        if isinstance(value, str):
            candidate = value.strip()
            parsed = urlparse(candidate)
            if (
                parsed.scheme != "https"
                or not parsed.netloc
                or candidate in seen
                or len(candidate) > 4096
            ):
                return
            seen.add(candidate)
            urls.append(candidate)
            return
        if isinstance(value, dict):
            for key in ("url_list", "urlList", "UrlList", "url", "Url", "playAddr", "PlayAddr"):
                if key in value:
                    add(value.get(key))
                    if len(urls) >= 6:
                        return
            return
        if isinstance(value, list):
            for child in value[:8]:
                add(child)
                if len(urls) >= 6:
                    return

    add(video.get("playAddr") or video.get("play_addr"))
    add(video.get("PlayAddrStruct"))
    add(video.get("downloadAddr") or video.get("download_addr"))
    add(video.get("bitrateInfo") or video.get("bitrate_info"))
    return urls


def download_image_b64(url: str) -> str | None:
    try:
        validate_public_url(url)
    except ValueError as exc:
        raise ExtractError(str(exc)) from exc
    content: bytes | None = None
    last_error: Exception | None = None
    for _ in range(2):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": UA, "Referer": "https://www.tiktok.com/"},
        )
        try:
            with safe_urlopen(req, timeout=30) as response:
                content = response.read(10_000_001)
            if len(content) > 10_000_000:
                raise ExtractError("Slide image is too large")
            break
        except ExtractError:
            raise
        except Exception as exc:
            last_error = exc
            content = None
    if content is None:
        error_type = type(last_error).__name__ if last_error else "UnknownError"
        raise ExtractError(f"Failed to download slide image: {error_type}") from last_error
    if len(content) < 500:
        return None
    encoded = base64.b64encode(content).decode("ascii")
    return encoded
