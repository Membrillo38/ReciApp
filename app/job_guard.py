from __future__ import annotations

import threading
from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException

from app.config import settings

_lock = threading.Lock()
_global_active = 0
_user_active: dict[UUID, int] = defaultdict(int)


def try_claim(user_id: UUID) -> bool:
    """Reserve one in-process slot. False when full — caller may leave job pending."""
    global _global_active
    with _lock:
        if _global_active >= settings.max_concurrent_jobs:
            return False
        if _user_active[user_id] >= settings.max_concurrent_jobs_per_user:
            return False
        _global_active += 1
        _user_active[user_id] += 1
        return True


def claim(user_id: UUID) -> None:
    if try_claim(user_id):
        return
    raise HTTPException(
        status_code=429,
        detail="Too many jobs in progress",
        headers={"Retry-After": "15"},
    )


def release(user_id: UUID) -> None:
    global _global_active
    with _lock:
        _global_active = max(0, _global_active - 1)
        _user_active[user_id] = max(0, _user_active[user_id] - 1)
        if not _user_active[user_id]:
            _user_active.pop(user_id, None)


def active_counts() -> tuple[int, int]:
    """Return (global_active, user_slot_count) for tests/dashboard."""
    with _lock:
        return _global_active, len(_user_active)
