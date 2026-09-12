from uuid import uuid4

from app import store
from app.auth_tokens import revoke_all_refresh_tokens
from app.main import admin_delete_user, delete_me


def test_soft_delete_clears_apple_identity(monkeypatch):
    captured = {}

    def fake_execute(sql, params=None):
        captured["sql"] = " ".join(sql.split())
        captured["params"] = params
        return 1

    monkeypatch.setattr(store, "execute", fake_execute)
    store.soft_delete_profile(uuid4())
    assert "apple_sub = null" in captured["sql"]
    assert "email = null" in captured["sql"]
    assert "deleted_at = coalesce(deleted_at, %s)" in captured["sql"]


def test_anonymize_deletes_user_library(monkeypatch):
    sqls = []

    def fake_execute(sql, params=None):
        sqls.append(" ".join(sql.split()))
        return 1

    monkeypatch.setattr(store, "execute", fake_execute)
    monkeypatch.setattr(store, "execute_returning", lambda *args, **kwargs: {"user_id": None})
    store.anonymize_user_data(uuid4())
    assert any("delete from user_recipes" in sql for sql in sqls)


def test_delete_me_revokes_tokens_before_soft_delete():
    source = open("app/main.py", encoding="utf-8").read()
    delete_body = source.split("def delete_me", 1)[1].split("def extract_recipe", 1)[0]
    assert delete_body.index("anonymize_user_data") < delete_body.index("revoke_all_refresh_tokens")
    assert delete_body.index("revoke_all_refresh_tokens") < delete_body.index("soft_delete_profile")
    assert "revoke_all_refresh_tokens" in source.split("def admin_delete_user", 1)[1].split("def admin_list_recipes", 1)[0]
    assert callable(delete_me) and callable(admin_delete_user) and callable(revoke_all_refresh_tokens)
