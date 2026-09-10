from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware

from app.cache import redis_rate_allow, reset_cache
from app.config import settings
import app.cache as cache
import app.main as main
import app.security as security


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.expires: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expires[key] = seconds

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        return None


def test_rate_limit_falls_back_without_redis(monkeypatch):
    monkeypatch.setattr(settings, "redis_url", "")
    reset_cache()
    security._rate_limiters.clear()
    assert security.allow_rate_limit("mem", limit=1, window_seconds=60)
    assert not security.allow_rate_limit("mem", limit=1, window_seconds=60)


def test_rate_limit_uses_redis_when_available(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(settings, "redis_url", "redis://reciapp-redis:6379/0")
    monkeypatch.setattr(cache, "_client", fake)
    monkeypatch.setattr(cache, "_failed_until", 0.0)
    assert redis_rate_allow("ip:1", limit=2, window_seconds=60) is True
    assert redis_rate_allow("ip:1", limit=2, window_seconds=60) is True
    assert redis_rate_allow("ip:1", limit=2, window_seconds=60) is False
    assert fake.expires["rl:60:2:ip:1"] == 60
    reset_cache()


def test_gzip_middleware_installed():
    names = [item.cls.__name__ for item in main.app.user_middleware]
    assert GZipMiddleware.__name__ in names
