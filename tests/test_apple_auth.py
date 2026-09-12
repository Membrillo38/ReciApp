from __future__ import annotations

import logging

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import apple_auth
from app.apple_auth import (
    create_apple_client_secret,
    decrypt_apple_refresh_token,
    encrypt_apple_refresh_token,
    exchange_apple_authorization_code,
    revoke_apple_refresh_token,
)
from app.config import settings
from app.models import AuthAppleRequest


def _p8() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _configure_apple(monkeypatch, pem: str | None = None) -> str:
    pem = pem or _p8()
    monkeypatch.setattr(settings, "apple_bundle_id", "com.membri.reciapp")
    monkeypatch.setattr(settings, "apple_team_id", "TEAM12ABCD")
    monkeypatch.setattr(settings, "apple_key_id", "KEYID12345")
    monkeypatch.setattr(settings, "apple_private_key", pem)
    monkeypatch.setattr(settings, "auth_jwt_secret", "test-auth-jwt-secret-material")
    monkeypatch.setattr(settings, "apple_token_encryption_key", "")
    return pem


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http_error")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, post_response, posts):
        self._post_response = post_response
        self.posts = posts

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, data=None, headers=None):
        self.posts.append({"url": url, "data": dict(data or {})})
        return self._post_response


def test_authorization_code_is_optional_on_apple_auth_request():
    body = AuthAppleRequest(identity_token="identity-token", nonce="nonce")
    assert body.authorization_code is None
    with_code = AuthAppleRequest(
        identity_token="identity-token",
        authorization_code="apple-auth-code",
    )
    assert with_code.authorization_code == "apple-auth-code"


def test_apple_refresh_token_roundtrip_is_not_plaintext(monkeypatch):
    _configure_apple(monkeypatch)
    raw = "apple-refresh-secret"
    ciphertext = encrypt_apple_refresh_token(raw)
    assert raw not in ciphertext
    assert decrypt_apple_refresh_token(ciphertext) == raw


def test_client_secret_jwt_is_short_lived_and_es256(monkeypatch):
    pem = _configure_apple(monkeypatch)
    secret = create_apple_client_secret()
    header = jwt.get_unverified_header(secret)
    claims = jwt.decode(
        secret,
        pem,
        algorithms=["ES256"],
        audience="https://appleid.apple.com",
    )
    assert header["alg"] == "ES256"
    assert header["kid"] == "KEYID12345"
    assert claims["iss"] == "TEAM12ABCD"
    assert claims["sub"] == "com.membri.reciapp"
    assert claims["exp"] - claims["iat"] == 300


def test_exchange_skips_when_apple_client_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "apple_team_id", "")
    monkeypatch.setattr(settings, "apple_key_id", "")
    monkeypatch.setattr(settings, "apple_private_key", "")
    assert exchange_apple_authorization_code("code", expected_sub="sub") is None


def test_exchange_stores_refresh_token_only_when_subject_matches(monkeypatch):
    _configure_apple(monkeypatch)
    posts = []
    monkeypatch.setattr(
        apple_auth,
        "_apple_http",
        lambda: FakeClient(
            FakeResponse(
                payload={
                    "refresh_token": "apple-refresh-secret",
                    "id_token": "exchanged-id-token",
                }
            ),
            posts,
        ),
    )
    monkeypatch.setattr(
        apple_auth,
        "verify_apple_identity_token",
        lambda token, nonce=None: apple_auth.AppleIdentity(apple_sub="apple-sub"),
    )
    assert exchange_apple_authorization_code("auth-code-secret", expected_sub="apple-sub") == "apple-refresh-secret"
    monkeypatch.setattr(
        apple_auth,
        "verify_apple_identity_token",
        lambda token, nonce=None: apple_auth.AppleIdentity(apple_sub="other-sub"),
    )
    assert exchange_apple_authorization_code("auth-code-secret", expected_sub="apple-sub") is None
    assert posts[0]["url"] == "https://appleid.apple.com/auth/token"
    assert posts[0]["data"]["grant_type"] == "authorization_code"
    assert posts[0]["data"]["code"] == "auth-code-secret"
    assert "client_secret" in posts[0]["data"]


def test_revoke_accepts_ok_and_invalid_grant(monkeypatch):
    _configure_apple(monkeypatch)
    posts = []
    monkeypatch.setattr(apple_auth, "_apple_http", lambda: FakeClient(FakeResponse(status_code=200), posts))
    assert revoke_apple_refresh_token("apple-refresh-secret") is True
    monkeypatch.setattr(
        apple_auth,
        "_apple_http",
        lambda: FakeClient(FakeResponse(status_code=400, payload={"error": "invalid_grant"}), posts),
    )
    assert revoke_apple_refresh_token("apple-refresh-secret") is True
    monkeypatch.setattr(apple_auth, "_apple_http", lambda: FakeClient(FakeResponse(status_code=500), posts))
    assert revoke_apple_refresh_token("apple-refresh-secret") is False
    assert posts[0]["url"] == "https://appleid.apple.com/auth/revoke"
    assert posts[0]["data"]["token_type_hint"] == "refresh_token"
    assert posts[0]["data"]["token"] == "apple-refresh-secret"


def test_apple_auth_logs_never_include_secrets(monkeypatch, caplog):
    _configure_apple(monkeypatch)
    posts = []
    monkeypatch.setattr(
        apple_auth,
        "_apple_http",
        lambda: FakeClient(FakeResponse(status_code=500, payload={"error": "server_error"}), posts),
    )
    caplog.set_level(logging.DEBUG)
    assert exchange_apple_authorization_code("auth-code-secret", expected_sub="apple-sub") is None
    assert revoke_apple_refresh_token("apple-refresh-secret") is False
    combined = caplog.text
    assert "auth-code-secret" not in combined
    assert "apple-refresh-secret" not in combined
    assert "BEGIN PRIVATE KEY" not in combined
    for post in posts:
        assert post["data"]["client_secret"] not in combined


def test_exchange_failure_does_not_raise(monkeypatch):
    _configure_apple(monkeypatch)
    monkeypatch.setattr(apple_auth, "create_apple_client_secret", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert exchange_apple_authorization_code("auth-code-secret", expected_sub="apple-sub") is None
