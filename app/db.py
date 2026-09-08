from __future__ import annotations

from threading import Lock

import httpx
from supabase import Client, ClientOptions, create_client

from app.config import settings

_KEEPALIVE_LIMITS = httpx.Limits(max_keepalive_connections=10, max_connections=50, keepalive_expiry=30)
_TRANSIENT_ERRORS = (
    httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.ReadTimeout,
    httpx.WriteError, httpx.WriteTimeout, httpx.RemoteProtocolError,
)


class ReadRetryTransport(httpx.BaseTransport):
    """Retry a safe read once, including failures while reading its response.

    Mutations are never replayed: a disconnect cannot prove whether an upstream
    write committed. HTTP status errors and local configuration errors are not
    transport retries. HTTPX's own connect retries stay disabled.
    """

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.transport = transport or httpx.HTTPTransport(http2=False, retries=0, limits=_KEEPALIVE_LIMITS)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        attempts = 2 if request.method in {"GET", "HEAD", "OPTIONS"} else 1
        for attempt in range(attempts):
            response = None
            try:
                response = self.transport.handle_request(request)
                # Consume inside the retry boundary; PostgREST/Auth return JSON.
                response.read()
                return response
            except _TRANSIENT_ERRORS:
                if attempt + 1 == attempts:
                    raise
            finally:
                if response is not None:
                    response.close()
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.transport.close()


def _prevent_sdk_status_retries(response: httpx.Response) -> None:
    # PostgREST 2.31 retries GET 503/520 three times by default. Status errors
    # are not transport failures; surface them before the SDK retry loop.
    if response.status_code in {503, 520}:
        response.raise_for_status()


def create_service_client(*, transport: httpx.BaseTransport | None = None) -> tuple[Client, httpx.Client]:
    """Build via the public SDK and return the HTTP client we own and must close."""
    settings.validate_supabase()
    http_client = httpx.Client(
        transport=ReadRetryTransport(transport),
        timeout=httpx.Timeout(settings.supabase_timeout_seconds),
        follow_redirects=False,
        trust_env=False,
        event_hooks={"response": [_prevent_sdk_status_retries]},
    )
    try:
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
            options=ClientOptions(
                httpx_client=http_client,
                persist_session=False,
                auto_refresh_token=False,
                postgrest_client_timeout=settings.supabase_timeout_seconds,
            ),
        )
        # Construct the lazy REST client now, without making a network request.
        client.table("profiles").select("id").limit(1)
        return client, http_client
    except Exception:
        http_client.close()
        raise RuntimeError("Supabase client initialization failed") from None


_client: Client | None = None
_http_client: httpx.Client | None = None
_client_lock = Lock()


def get_supabase() -> Client:
    global _client, _http_client
    with _client_lock:
        if _client is None:
            _client, _http_client = create_service_client()
        return _client


def reset_supabase() -> None:
    """Close owned resources after requests/workers drain, at process shutdown.

    Never call this on individual request failures: that would close a shared
    pool while other requests still use it. HTTPX discards broken connections.
    """
    global _client, _http_client
    with _client_lock:
        if _http_client is not None:
            _http_client.close()
        _client = None
        _http_client = None


async def probe_supabase() -> None:
    """One bounded async REST read; caller supplies an overall deadline."""
    async with httpx.AsyncClient(
        timeout=settings.readiness_timeout_seconds, follow_redirects=False, trust_env=False,
    ) as client:
        response = await client.get(
            settings.supabase_url.rstrip("/") + "/rest/v1/profiles",
            params={"select": "id", "limit": "1"},
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": "Bearer " + settings.supabase_service_role_key,
                "Accept-Profile": "public",
            },
        )
        response.raise_for_status()
        if not isinstance(response.json(), list):
            raise ValueError("Invalid readiness response")
