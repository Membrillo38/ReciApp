from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app import auth
from app.config import settings


def _admin_request(*, origin: str | None = None) -> Request:
    headers = []
    if origin:
        headers.append((b"origin", origin.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/admin/users",
            "headers": headers,
            "client": ("203.0.113.10", 1234),
        }
    )


def test_require_api_key_rejects_foreign_origin(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-admin-key")
    monkeypatch.setattr(settings, "cors_origins", "https://51-255-43-100.sslip.io")
    with pytest.raises(HTTPException) as exc:
        auth.require_api_key(_admin_request(origin="https://evil.example"), x_api_key="secret-admin-key")
    assert exc.value.status_code == 403


def test_require_api_key_allows_cors_origin(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-admin-key")
    monkeypatch.setattr(settings, "cors_origins", "https://51-255-43-100.sslip.io")
    auth.require_api_key(
        _admin_request(origin="https://51-255-43-100.sslip.io"),
        x_api_key="secret-admin-key",
    )


def test_require_api_key_allows_missing_origin(monkeypatch):
    # Native / curl / scripts have no Origin header.
    monkeypatch.setattr(settings, "api_key", "secret-admin-key")
    auth.require_api_key(_admin_request(origin=None), x_api_key="secret-admin-key")
