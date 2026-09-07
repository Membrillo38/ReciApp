from __future__ import annotations

import threading
from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException

from app.config import settings

_lock = threading.Lock()
_global_active = 0
_user_active: dict[UUID, int] = defaultdict(int)


def claim(user_id: UUID) -> None:
    global _global_active
    with _lock:
        if _global_active >= settings.max_concurrent_jobs:
            raise HTTPException(status_code=429, detail="Too many jobs in progress")
        if _user_active[user_id] >= settings.max_concurrent_jobs_per_user:
            raise HTTPException(status_code=429, detail="Too many jobs in progress for this user")
        _global_active += 1
        _user_active[user_id] += 1


def release(user_id: UUID) -> None:
    global _global_active
    with _lock:
        _global_active = max(0, _global_active - 1)
        _user_active[user_id] = max(0, _user_active[user_id] - 1)
        if not _user_active[user_id]:
            _user_active.pop(user_id, None)
