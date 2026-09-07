from __future__ import annotations

import hmac
import secrets

from fastapi import Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings
from app.security import safe_compare

COOKIE_NAME = "reciapp_admin"
COOKIE_MAX_AGE = 60 * 60 * 12  # 12h


def _serializer() -> URLSafeTimedSerializer:
    secret = settings.dashboard_session_secret
    if not secret:
        # Fail closed: never derive a dashboard session from an API key/password.
        secret = secrets.token_urlsafe(32)
    return URLSafeTimedSerializer(secret, salt="reciapp-dashboard-v1")


def dashboard_enabled() -> bool:
    return bool(
        settings.dashboard_password
        and settings.dashboard_session_secret
        and settings.dashboard_totp_secret
    )


def verify_password(password: str) -> bool:
    expected = settings.dashboard_password
    if not expected:
        return False
    return safe_compare(password, expected)


def verify_totp(code: str) -> bool:
    if not settings.dashboard_totp_secret:
        return False
    try:
        import pyotp

        return bool(pyotp.TOTP(settings.dashboard_totp_secret).verify(code, valid_window=1))
    except Exception:
        return False


def create_session_token() -> str:
    return _serializer().dumps({"role": "admin", "mfa": True, "nonce": secrets.token_hex(8)})


def read_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        data = _serializer().loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("role") == "admin" and data.get("mfa") is True
    except BadSignature:
        return False
    except Exception:
        return False


def set_session_cookie(response: RedirectResponse, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=bool(settings.dashboard_cookie_secure),
        samesite="strict",
        max_age=COOKIE_MAX_AGE,
        path="/dashboard",
    )


def clear_session_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(COOKIE_NAME, path="/dashboard")


def csrf_for_request(request: Request) -> str:
    cookie = request.cookies.get(COOKIE_NAME) or ""
    key = settings.dashboard_session_secret.encode()
    return hmac.new(key, cookie.encode(), "sha256").hexdigest()


def csrf_matches(request: Request, value: str) -> bool:
    return safe_compare(value, csrf_for_request(request))
