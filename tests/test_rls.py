from __future__ import annotations

from pathlib import Path

from app.db import db_context, db_context_for_request


def test_rls_migration_forces_policies_and_fail_closed_helpers():
    migration = Path("migrations/002_row_level_security.sql").read_text(encoding="utf-8")
    assert "force row level security" in migration
    assert "create policy reciapp_service" in migration
    assert "create policy profiles_self" in migration
    assert "create policy extract_jobs_select" in migration
    assert "create policy extract_jobs_update" in migration
    assert "create policy auth_refresh_tokens_self" in migration
    assert "app.actor" in migration
    assert "app.user_id" in migration
    assert "perform set_config('app.actor', 'service', true)" in migration


def test_db_context_for_request_routes():
    user = "11111111-1111-1111-1111-111111111111"
    assert db_context_for_request("/dashboard", None) == ("service", "")
    assert db_context_for_request("/v1/admin/users", user) == ("service", "")
    assert db_context_for_request("/v1/webhooks/apple", None) == ("service", "")
    assert db_context_for_request("/v1/auth/apple", None) == ("auth", "")
    assert db_context_for_request("/v1/auth/logout", user) == ("auth", user)
    assert db_context_for_request("/v1/me", user) == ("user", user)
    assert db_context_for_request("/v1/me", None) == ("", "")
    assert db_context_for_request("/health", None) == ("", "")


def test_db_context_resets_after_block():
    from app import db as dbmod

    with db_context(actor="user", user_id="abc"):
        assert dbmod._db_actor.get() == "user"
        assert dbmod._db_user_id.get() == "abc"
    assert dbmod._db_actor.get() == ""
    assert dbmod._db_user_id.get() == ""
