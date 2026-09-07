from __future__ import annotations

import hashlib
import hmac
import ipaddress
import secrets
import socket
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request as URLRequest, build_opener

from fastapi import HTTPException, Request

from app.db import get_supabase


def request_ip(request: Request) -> str:
    """Return the edge-provided client IP without logging proxy chains."""
    forwarded = request.headers.get("x-forwarded-for", "")
    candidate = forwarded.split(",", 1)[0].strip() if forwarded else ""
    candidate = candidate or (request.client.host if request.client else "unknown")
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return "unknown"


def pseudonymous_ip(value: str | None) -> str | None:
    if not value:
        return None
    # Stable enough for abuse analysis, but never stores the raw address.
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"sha256:{digest[:32]}"


def audit_security_event(
    *,
    event: str,
    request: Request | None = None,
    user_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Best-effort audit. Never include credentials or request bodies."""
    try:
        get_supabase().table("security_events").insert(
            {
                "event": event[:80],
                "user_id": user_id,
                "ip": pseudonymous_ip(request_ip(request)) if request else None,
                "metadata": metadata or {},
            }
        ).execute()
    except Exception:
        pass


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)
            return True


_rate_limiter: SlidingWindowLimiter | None = None


def allow_rate_limit(key: str, *, limit: int, window_seconds: int) -> bool:
    global _rate_limiter
    if _rate_limiter is None or (
        _rate_limiter.limit != max(1, limit)
        or _rate_limiter.window_seconds != max(1, window_seconds)
    ):
        _rate_limiter = SlidingWindowLimiter(limit, window_seconds)
    return _rate_limiter.allow(key)


def require_rate_limit(
    request: Request,
    *,
    key: str,
    limit: int,
    window_seconds: int,
    event: str,
) -> None:
    if allow_rate_limit(key, limit=limit, window_seconds=window_seconds):
        return
    audit_security_event(event=event, request=request)
    raise HTTPException(status_code=429, detail="Too many requests")


def validate_public_url(url: str, *, allowed_hosts: set[str] | None = None) -> None:
    """Reject non-HTTPS, ambiguous, local and metadata URLs before fetching."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https" or not host or parsed.username or parsed.password:
        raise ValueError("Only public HTTPS URLs are accepted")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL port") from exc
    if port not in (None, 443):
        raise ValueError("Non-standard ports are not accepted")
    if allowed_hosts and not any(host == item or host.endswith(f".{item}") for item in allowed_hosts):
        raise ValueError("Unsupported source host")
    addresses: list[str]
    try:
        addresses = [item[4][0] for item in socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)]
    except socket.gaierror as exc:
        raise ValueError("URL host could not be resolved") from exc
    for raw_address in set(addresses):
        try:
            address = ipaddress.ip_address(raw_address)
        except ValueError as exc:
            raise ValueError("Invalid URL address") from exc
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        ):
            raise ValueError("Private or metadata addresses are not accepted")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = build_opener(_SafeRedirectHandler())


def safe_urlopen(request: URLRequest, *, timeout: int):
    validate_public_url(request.full_url)
    return _SAFE_OPENER.open(request, timeout=timeout)


def safe_compare(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def new_correlation_id() -> str:
    return secrets.token_urlsafe(12)
