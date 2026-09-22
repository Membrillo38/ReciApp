from __future__ import annotations

import logging
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

from app.config import settings

logger = logging.getLogger(__name__)

AUTH_PATHS = ("/v1/auth/", "/v1/me")


def init_sentry() -> None:
    """Initialize Sentry without making DSN mandatory for local/test runs."""
    if not settings.sentry_dsn:
        return
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=settings.sentry_release or None,
        integrations=[FastApiIntegration(), StarletteIntegration()],
        send_default_pii=False,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        before_send=_scrub_event,
    )


def _scrub_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    """Remove request payloads and known credential fields before transport."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in ("authorization", "cookie", "x-api-key"):
                headers.pop(key, None)
    for container_name in ("extra", "contexts"):
        container = event.get(container_name)
        if isinstance(container, dict):
            _scrub_mapping(container)
    return event


def _scrub_mapping(value: dict[str, Any]) -> None:
    secret_names = {"identitytoken", "authorizationcode", "accesstoken", "refreshtoken", "password", "cookie", "body"}
    for key in list(value):
        if key.lower().replace("_", "") in secret_names:
            value[key] = "[Filtered]"
        elif isinstance(value[key], dict):
            _scrub_mapping(value[key])


def auth_error(
    *, request: Any, code: str, phase: str, status: int, exc: BaseException | None = None,
    level: str = "error", message: str | None = None,
) -> None:
    """Capture auth failure with correlation metadata, never token values."""
    data = {
        "auth_flow": "apple" if request.url.path.endswith("/apple") else "session",
        "auth_phase": phase,
        "auth_endpoint": request.url.path,
        "http_status": status,
        "server_code": code,
        "request_id": getattr(request.state, "request_id", "unknown"),
        "correlation_id": getattr(request.state, "correlation_id", "unknown"),
        "release": settings.sentry_release or "",
        "environment": settings.sentry_environment,
    }
    with sentry_sdk.new_scope() as scope:
        for key, value in data.items():
            scope.set_tag(key, str(value))
        scope.set_context("auth", {"phase": phase, "endpoint": request.url.path, "code": code})
        if exc is not None and level == "error":
            sentry_sdk.capture_exception(exc)
        else:
            scope.set_level(level)
            sentry_sdk.capture_message(message or code)
