"""Fail-closed stress-test guards and local mock helpers.

Never enable against production DB or with live provider keys.
"""

from __future__ import annotations

import hashlib
import random
import time
from urllib.parse import urlsplit

from app.config import settings

STRESS_HOST_DEFAULT = "stress-test.local"


def stress_hosts() -> set[str]:
    raw = (settings.stress_allowed_hosts or STRESS_HOST_DEFAULT).strip()
    return {h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip()}


def is_stress_host(host: str | None) -> bool:
    if not host:
        return False
    return host.lower().rstrip(".") in stress_hosts()


def is_stress_url(url: str) -> bool:
    try:
        return is_stress_host(urlsplit(url).hostname)
    except Exception:
        return False


def assert_stress_safe() -> None:
    """Raise before serving if STRESS_TEST_MODE is misconfigured."""
    if not settings.stress_test_mode:
        return

    db = (settings.database_url or "").lower()
    if "stress" not in db:
        raise RuntimeError("STRESS_TEST_MODE requires DATABASE_URL name/credentials containing 'stress'")

    parsed = urlsplit(settings.database_url)
    db_name = (parsed.path or "").lstrip("/").split("?")[0].lower()
    if "stress" not in db_name:
        raise RuntimeError("STRESS_TEST_MODE requires database name containing 'stress'")

    env = (settings.environment or "").lower()
    if env not in {"stress", "stress-test"}:
        raise RuntimeError("STRESS_TEST_MODE requires ENVIRONMENT=stress")

    if (settings.openai_api_key or "").strip():
        raise RuntimeError("STRESS_TEST_MODE forbids OPENAI_API_KEY")

    public = (settings.public_api_base_url or "").lower()
    blocked = ("51-255-43-100.sslip.io", "onrender.com", "supabase.co")
    if any(b in public for b in blocked) and "stress" not in public:
        raise RuntimeError("STRESS_TEST_MODE refuses production PUBLIC_API_BASE_URL")

    if not (settings.stress_token or "").strip():
        raise RuntimeError("STRESS_TEST_MODE requires STRESS_TOKEN")

    if not (settings.auth_jwt_secret or "").strip():
        raise RuntimeError("STRESS_TEST_MODE requires AUTH_JWT_SECRET")

    if not (settings.api_key or "").strip():
        raise RuntimeError("STRESS_TEST_MODE requires API_KEY")


def mock_should_fail(seed: str) -> bool:
    pct = float(settings.stress_mock_fail_pct or 0.0)
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    digest = hashlib.sha256(f"{settings.stress_run_id}:{seed}".encode()).hexdigest()
    bucket = int(digest[:8], 16) % 10_000
    return bucket < int(pct * 100)


def mock_hold_ms(seed: str) -> int:
    """Deterministic hold from fixed ms or [min,max] range."""
    fixed = int(settings.stress_mock_latency_ms or 0)
    lo = int(settings.stress_mock_latency_min_ms or 0)
    hi = int(settings.stress_mock_latency_max_ms or 0)
    if hi > lo > 0:
        rng = random.Random(f"{settings.stress_run_id}:{seed}")
        return int(rng.randint(lo, hi))
    return max(0, fixed)


def apply_mock_latency(seed: str) -> int:
    hold = mock_hold_ms(seed)
    if hold > 0:
        time.sleep(hold / 1000.0)
    return hold
