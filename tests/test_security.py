from __future__ import annotations

import socket

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.security as security


def _request(*, client: str, xff: str | None = None) -> Request:
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/me",
            "headers": headers,
            "client": (client, 1234),
        }
    )


def test_validate_public_url_blocks_private_and_metadata(monkeypatch):
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host == "internal.example":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(security.socket, "getaddrinfo", fake_getaddrinfo)

    for url in (
        "http://localhost/",
        "https://metadata.google.internal/",
        "http://169.254.169.254/latest/meta-data",
        "https://[fd00::1]/",
        "http://internal.example/",
        "ftp://example.com/file",
        "http://example.com:8080/",
        "https://example.com:8443/",
    ):
        with pytest.raises(ValueError):
            security.validate_public_url(url)

    security.validate_public_url("http://example.com/")
    security.validate_public_url("https://example.com:443/")


def test_request_ip_ignores_xff_from_untrusted_client(monkeypatch):
    monkeypatch.setattr(security.settings, "trusted_proxy_ips", "")

    request = _request(client="203.0.113.10", xff="1.1.1.1, 2.2.2.2")

    assert security.request_ip(request) == "203.0.113.10"


def test_request_ip_honors_xff_from_trusted_client(monkeypatch):
    monkeypatch.setattr(security.settings, "trusted_proxy_ips", "203.0.113.0/24")

    request = _request(client="203.0.113.10", xff="1.1.1.1, 2.2.2.2")

    assert security.request_ip(request) == "1.1.1.1"


def test_ban_ladder_escalates(monkeypatch):
    now = 1_000.0
    monkeypatch.setattr(security.time, "monotonic", lambda: now)
    security._ban_states.clear()

    key = "ip:198.51.100.7"

    assert security.record_rate_limit_violation(key) is None
    assert security.record_rate_limit_violation(key) is None
    assert security.record_rate_limit_violation(key) == 5 * 60

    now += 5 * 60 + 1
    assert security.record_rate_limit_violation(key) is None
    assert security.record_rate_limit_violation(key) is None
    assert security.record_rate_limit_violation(key) == 60 * 60

    now += 60 * 60 + 1
    assert security.record_rate_limit_violation(key) is None
    assert security.record_rate_limit_violation(key) is None
    assert security.record_rate_limit_violation(key) == 24 * 60 * 60

    with pytest.raises(HTTPException) as caught:
        security.raise_if_banned(key)
    assert caught.value.status_code == 429
    assert caught.value.headers["Retry-After"] == str(24 * 60 * 60)
