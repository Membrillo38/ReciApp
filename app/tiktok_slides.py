from __future__ import annotations

import base64
import json
import re
import urllib.request
from dataclasses import dataclass

from app.extract import ExtractError

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class SlideInfo:
    title: str
    description: str
    author: str | None
    image_urls: list[str]
    ocr_text: str | None = None


def fetch_tiktok_slides(url: str) -> SlideInfo | None:
    html = _fetch_html(url)
    if not html:
        return None

    item = _item_from_html(html)
    if not item:
        return None

    image_post = item.get("imagePost") or {}
    images: list[str] = []
    for image in image_post.get("images") or []:
        urls = ((image.get("imageURL") or {}).get("urlList")) or []
        if urls:
            images.append(urls[0])

    if not images:
        return None

    stats = item.get("stats") or {}
    _ = stats  # reserved for future metadata

    return SlideInfo(
        title=(image_post.get("title") or item.get("desc") or "").strip(),
        description=(item.get("desc") or "").strip(),
        author=((item.get("author") or {}).get("uniqueId")),
        image_urls=images,
    )


def _fetch_html(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
    except Exception:
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
        return next(iter(item_module.values()))
    return None


def download_image_b64(url: str) -> str | None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": UA, "Referer": "https://www.tiktok.com/"},
    )
    try:
        content = urllib.request.urlopen(req, timeout=30).read()
    except Exception as exc:
        raise ExtractError(f"Failed to download slide image: {exc}") from exc
    if len(content) < 500:
        return None
    encoded = base64.b64encode(content).decode("ascii")
    return encoded
