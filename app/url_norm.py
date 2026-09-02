from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.models import Platform
from app.platforms import detect_platform, youtube_video_id

_DROP_QUERY = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "igshid",
    "igsh",
    "si",
    "feature",
    "pp",
    "ref",
}


def normalize_url(url: str) -> str:
    raw = url.strip()
    parsed = urlparse(raw)
    scheme = "https"
    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host_core = host[4:]
    else:
        host_core = host

    platform = detect_platform(raw)

    if platform == Platform.youtube:
        vid = youtube_video_id(raw)
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"

    if platform == Platform.tiktok:
        host = "www.tiktok.com"
        path = parsed.path.rstrip("/")
        # /@user/video/ID or /video/ID or short /t/...
        return urlunparse((scheme, host, path, "", "", ""))

    if platform == Platform.instagram:
        host = "www.instagram.com"
        path = parsed.path.rstrip("/")
        return urlunparse((scheme, host, path, "", "", ""))

    if platform == Platform.facebook:
        host = host if host else "www.facebook.com"
        if "fb.watch" in host_core:
            host = "fb.watch"
        path = parsed.path.rstrip("/")
        return urlunparse((scheme, host, path, "", "", ""))

    # generic: strip tracking query params
    qs = parse_qs(parsed.query, keep_blank_values=False)
    cleaned = {k: v for k, v in qs.items() if k.lower() not in _DROP_QUERY}
    query = urlencode(cleaned, doseq=True)
    path = parsed.path.rstrip("/") or parsed.path
    return urlunparse((scheme, host or host_core, path, "", query, ""))
