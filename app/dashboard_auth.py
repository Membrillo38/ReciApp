from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings

COOKIE_NAME = "reciapp_admin"
COOKIE_MAX_AGE = 60 * 60 * 12  # 12h


def _serializer() -> URLSafeTimedSerializer:
    secret = settings.dashboard_session_secret or settings.api_key or settings.dashboard_password or "dev-insecure"
    return URLSafeTimedSerializer(secret, salt="reciapp-dashboard-v1")


def dashboard_enabled() -> bool:
    return bool(settings.dashboard_password)


def verify_password(password: str) -> bool:
    expected = settings.dashboard_password
    if not expected:
        return False
    return hmac.compare_digest(password.encode("utf-8"), expected.encode("utf-8"))


def create_session_token() -> str:
    return _serializer().dumps({"role": "admin", "nonce": secrets.token_hex(8)})


def read_session_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        data = _serializer().loads(token, max_age=COOKIE_MAX_AGE)
        return data.get("role") == "admin"
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
    key = (
        settings.dashboard_session_secret
        or settings.dashboard_password
        or "x"
    ).encode()
    return hmac.new(key, cookie.encode(), "sha256").hexdigest()
