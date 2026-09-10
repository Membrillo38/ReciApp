from __future__ import annotations

import threading
import time
from typing import Any

from app.config import settings

_client: Any = None
_lock = threading.Lock()
_failed_until = 0.0
_FAIL_BACKOFF_SECONDS = 5.0


def reset_cache() -> None:
    global _client, _failed_until
    with _lock:
        client = _client
        _client = None
        _failed_until = 0.0
    if client:
        try:
            client.close()
        except Exception:
            pass


def get_redis() -> Any | None:
    """Return a live Redis client, or None to use in-process fallbacks."""
    global _client, _failed_until
    url = (settings.redis_url or "").strip()
    if not url:
        return None
    now = time.monotonic()
    with _lock:
        if _client is not None:
            return _client
        if now < _failed_until:
            return None
        try:
            import redis as redis_lib

            client = redis_lib.Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.2,
                socket_timeout=0.2,
            )
            client.ping()
            _client = client
            return client
        except Exception:
            _failed_until = now + _FAIL_BACKOFF_SECONDS
            return None


def redis_rate_allow(key: str, *, limit: int, window_seconds: int) -> bool | None:
    """Fixed-window counter. None means caller should use the memory limiter."""
    client = get_redis()
    if client is None:
        return None
    redis_key = f"rl:{window_seconds}:{limit}:{key}"
    try:
        current = int(client.incr(redis_key))
        if current == 1:
            client.expire(redis_key, window_seconds)
        return current <= limit
    except Exception:
        reset_cache()
        return None
