import os
from urllib.parse import urlsplit

import pytest

from app.config import Settings
from app.stress_mode import assert_stress_safe, is_stress_url, mock_should_fail


def test_assert_stress_safe_requires_stress_db(monkeypatch):
    monkeypatch.setenv("STRESS_TEST_MODE", "true")
    monkeypatch.setenv("ENVIRONMENT", "stress")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/reciapp")
    monkeypatch.setenv("STRESS_TOKEN", "tok")
    monkeypatch.setenv("AUTH_JWT_SECRET", "secret")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "http://127.0.0.1:18000")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        from app import stress_mode

        s = Settings()
        monkeypatch.setattr(stress_mode, "settings", s)
        assert_stress_safe()


def test_assert_stress_safe_blocks_openai(monkeypatch):
    monkeypatch.setenv("STRESS_TEST_MODE", "true")
    monkeypatch.setenv("ENVIRONMENT", "stress")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/reciapp_stress")
    monkeypatch.setenv("STRESS_TOKEN", "tok")
    monkeypatch.setenv("AUTH_JWT_SECRET", "secret")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "http://127.0.0.1:18000")
    from app import stress_mode

    s = Settings()
    monkeypatch.setattr(stress_mode, "settings", s)
    with pytest.raises(RuntimeError, match="OPENAI"):
        assert_stress_safe()


def test_assert_stress_safe_ok(monkeypatch):
    monkeypatch.setenv("STRESS_TEST_MODE", "true")
    monkeypatch.setenv("ENVIRONMENT", "stress")
    monkeypatch.setenv("DATABASE_URL", "postgresql://reciapp_stress:x@db:5432/reciapp_stress")
    monkeypatch.setenv("STRESS_TOKEN", "tok")
    monkeypatch.setenv("AUTH_JWT_SECRET", "secret")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "http://127.0.0.1:18000")
    from app import stress_mode

    s = Settings()
    monkeypatch.setattr(stress_mode, "settings", s)
    assert_stress_safe()


def test_validate_public_url_skips_dns_for_stress(monkeypatch):
    from app import security
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "stress_test_mode", True)
    monkeypatch.setattr(app_settings, "stress_allowed_hosts", "stress-test.local")
    security.validate_public_url(
        "https://stress-test.local/recipe/1",
        allowed_hosts={"stress-test.local"},
    )


def test_stress_url_and_fail_bucket(monkeypatch):
    from app import stress_mode
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "stress_test_mode", True)
    monkeypatch.setattr(app_settings, "stress_run_id", "run1")
    monkeypatch.setattr(app_settings, "stress_mock_fail_pct", 100.0)
    monkeypatch.setattr(app_settings, "stress_allowed_hosts", "stress-test.local")
    assert is_stress_url("https://stress-test.local/recipe/1")
    assert mock_should_fail("any")
    assert urlsplit("https://stress-test.local/x").hostname == "stress-test.local"
