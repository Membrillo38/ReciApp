"""Admission failures must never exhaust the local processing capacity."""
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks
from starlette.requests import Request

import app.main as main
from app.auth import AuthUser


@pytest.mark.parametrize("kind", ["extract", "translation"])
@pytest.mark.parametrize("failure", ["reservation_and_update", "create_and_lookup", "create_and_share"])
def test_failed_admission_releases_capacity(monkeypatch, kind, failure):
    user = AuthUser(uuid4(), None, None, False, None)
    claims, releases = [], []
    monkeypatch.setattr(main.settings, "worker_enabled", False)
    monkeypatch.setattr(main.settings, "openai_api_key", "test")
    monkeypatch.setattr(main, "claim_job", lambda uid: claims.append(uid))
    monkeypatch.setattr(main, "release_job", lambda uid: releases.append(uid))
    for name in ("require_rate_limit", "validate_public_url", "assert_can_extract"):
        monkeypatch.setattr(main, name, lambda *a, **kw: None)
    monkeypatch.setattr(main, "get_recipe_by_norm", lambda *a: None)
    monkeypatch.setattr(main, "_expire_stale_job", lambda *a: False)

    def broken(*a, **kw):
        raise RuntimeError("database unavailable")

    lookups = []
    def lookup(**kw):
        lookups.append(True)
        if len(lookups) == 1:
            return None
        if failure == "create_and_lookup":
            return broken()
        return {"id": str(uuid4()), "user_id": str(uuid4()), "status": "pending"}

    monkeypatch.setattr(main, "get_active_job", lookup)
    monkeypatch.setattr(main, "_share_job_or_http", broken)
    monkeypatch.setattr(main, "create_job", (lambda **kw: {"id": str(uuid4())}) if failure == "reservation_and_update" else broken)
    monkeypatch.setattr(main, "reserve_spend", broken)
    monkeypatch.setattr(main, "update_job", broken)
    background = BackgroundTasks()
    with pytest.raises(RuntimeError, match="database unavailable"):
        if kind == "translation":
            main._ensure_translation_job(user=user, recipe_id=uuid4(), source_url_raw="https://youtu.be/test", source_url_norm="youtube:test", language_code="es-ES", background=background)
        else:
            request = Request({"type": "http", "method": "POST", "path": "/v1/extract", "headers": [], "client": ("127.0.0.1", 1234)})
            main.extract_recipe(request, main.ExtractRequest(url="https://youtu.be/test"), background, user)
    assert claims == [user.id]
    assert releases == [user.id]
    assert background.tasks == []
