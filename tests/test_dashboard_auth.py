from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse

from app import dashboard_auth, dashboard_routes
from app.config import settings


def _request(path: str = "/dashboard") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [(b"host", b"100.123.33.15:8090")],
            "client": ("100.123.33.15", 1234),
        }
    )


def test_dashboard_fails_closed_without_totp(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_password", "password")
    monkeypatch.setattr(settings, "dashboard_session_secret", "session-secret")
    monkeypatch.setattr(settings, "dashboard_totp_secret", "")

    assert not dashboard_auth.dashboard_enabled()
    assert not dashboard_auth.verify_totp("123456")


def test_dashboard_redirects_without_authenticated_session(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_password", "password")
    monkeypatch.setattr(settings, "dashboard_session_secret", "session-secret")
    monkeypatch.setattr(settings, "dashboard_totp_secret", "JBSWY3DPEHPK3PXP")

    response = dashboard_routes._require_admin(_request("/dashboard/users"))

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/dashboard/login?next=/dashboard/users")


def test_production_dashboard_cookie_cannot_be_downgraded(monkeypatch):
    monkeypatch.setattr(settings, "dashboard_cookie_secure", False)
    monkeypatch.setattr(settings, "environment", "production")
    response = RedirectResponse("/dashboard")

    dashboard_auth.set_session_cookie(response, "signed-session")

    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=strict" in cookie
