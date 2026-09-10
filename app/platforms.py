from __future__ import annotations

import re
from urllib.parse import urlparse

from app.models import Platform

_YOUTUBE = re.compile(
    r"(?:youtube\.com/(?:watch\?.*v=|shorts/|embed/)|youtu\.be/)",
    re.I,
)
_TIKTOK = re.compile(r"tiktok\.com/", re.I)
_INSTAGRAM = re.compile(r"instagram\.com/(?:reel|p|tv)/", re.I)
_FACEBOOK = re.compile(r"(?:facebook\.com|fb\.watch)", re.I)


def detect_platform(url: str) -> Platform:
    if _TIKTOK.search(url):
        return Platform.tiktok
    if _YOUTUBE.search(url):
        return Platform.youtube
    if _INSTAGRAM.search(url):
        return Platform.instagram
    if _FACEBOOK.search(url):
        return Platform.facebook
    return Platform.unknown


def youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path or ""

    if "youtu.be" in host:
        vid = path.strip("/").split("/")[0]
        return vid or None

    if "youtube.com" in host:
        if "/shorts/" in path:
            return path.split("/shorts/", 1)[1].split("/")[0] or None
        if "/embed/" in path:
            return path.split("/embed/", 1)[1].split("/")[0] or None
        from urllib.parse import parse_qs

        qs = parse_qs(parsed.query)
        if "v" in qs and qs["v"]:
            return qs["v"][0]

    return None
