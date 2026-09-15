"""EXTRACT_DRY_RUN completes miss path without providers."""
from uuid import uuid4

import app.pipeline as pipeline
from app.models import JobStatus


def test_dry_run_persists_recipe_and_releases_slot(monkeypatch):
    job_id = uuid4()
    user_id = uuid4()
    updates = []
    releases = []
    drains = []

    monkeypatch.setattr(pipeline.settings, "extract_dry_run", True)
    monkeypatch.setattr(pipeline.settings, "extract_dry_run_hold_ms", 0)
    monkeypatch.setattr(pipeline.settings, "maintenance_mode", False)
    monkeypatch.setattr(pipeline, "update_job", lambda jid, **kw: updates.append((jid, kw)))
    monkeypatch.setattr(pipeline, "upsert_recipe", lambda recipe, **kw: {"id": uuid4()})
    monkeypatch.setattr(pipeline, "save_user_recipe", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "record_usage", lambda **kw: None)
    monkeypatch.setattr(pipeline, "settle_spend", lambda **kw: None)
    monkeypatch.setattr(pipeline, "release_job", lambda uid: releases.append(uid))
    monkeypatch.setattr(pipeline, "_drain_next_extract_for_user", lambda uid: drains.append(uid))

    pipeline._run_extract_job(
        job_id,
        user_id,
        "https://youtu.be/dryruntest01",
        "youtube:dryruntest01",
        "en-US",
    )

    assert releases == [user_id]
    assert drains == [user_id]
    statuses = [kw.get("status") for _, kw in updates if "status" in kw]
    assert JobStatus.processing.value in statuses
    assert JobStatus.completed.value in statuses
    completed = next(kw for _, kw in updates if kw.get("status") == JobStatus.completed.value)
    assert completed.get("cost_cents") == 0
    assert completed.get("cache_hit") is False
