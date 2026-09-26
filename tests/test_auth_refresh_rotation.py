from uuid import uuid4
from types import SimpleNamespace

from app import auth_tokens, main


def test_refresh_rotation_revokes_and_issues_in_one_statement(monkeypatch):
    user_id = uuid4()
    calls = []

    def execute_returning(sql, params):
        calls.append((sql, params))
        return {"user_id": user_id, "email": "person@example.com"}

    monkeypatch.setattr(auth_tokens, "execute_returning", execute_returning)
    monkeypatch.setattr(auth_tokens, "create_access_token", lambda received_id, email: "access")
    monkeypatch.setattr(auth_tokens.settings, "auth_refresh_token_ttl_seconds", 3600)

    result = auth_tokens.rotate_refresh_token("old-refresh")

    assert result is not None
    assert result["access_token"] == "access"
    assert result["refresh_token"] != "old-refresh"
    assert len(calls) == 1
    sql, params = calls[0]
    assert "with revoked as" in sql.lower()
    assert "issued as" in sql.lower()
    assert params[0] == auth_tokens._hash("old-refresh")
    assert params[1] == auth_tokens._hash(result["refresh_token"])


def test_refresh_rotation_returns_none_for_missing_or_expired_token(monkeypatch):
    monkeypatch.setattr(auth_tokens, "execute_returning", lambda *_: None)
    assert auth_tokens.rotate_refresh_token("invalid") is None


def test_profile_preserves_legacy_quota_field_and_returns_yearly_field(monkeypatch):
    user_id = uuid4()
    monkeypatch.setattr(
        main,
        "get_quota",
        lambda _: SimpleNamespace(
            free_used_this_week=2,
            free_limit=3,
            free_remaining=1,
            pro_remaining_cents=0,
        ),
    )

    result = main.me(SimpleNamespace(
        id=user_id,
        display_name="Test",
        is_pro=False,
        pro_expires_at=None,
    ))

    assert result.free_used_this_week == 2
    assert result.free_used_this_year == 2
