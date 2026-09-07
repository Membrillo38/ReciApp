from __future__ import annotations

from functools import lru_cache

from httpx import Client as HTTPXClient, Limits
from postgrest import SyncPostgrestClient
from supabase import Client
from supabase._sync.auth_client import SyncSupabaseAuthClient
from supabase._sync.client import SyncClient

from app.config import settings


_KEEPALIVE_LIMITS = Limits(
    max_keepalive_connections=10,
    max_connections=50,
    keepalive_expiry=30,
)


def _http_client(*, timeout: int | float = 30, verify: bool = True, proxy: str | None = None) -> HTTPXClient:
    """Create a stable HTTP/1.1 client for Supabase's synchronous SDK.

    supabase-py 2.11.0 enables HTTP/2 in both PostgREST and GoTrue. Render
    logs showed intermittent ``RemoteProtocolError: Server disconnected``
    failures on those connections. HTTP/1.1 with bounded keep-alives avoids
    the broken multiplexed connection while retaining connection reuse.
    """
    return HTTPXClient(
        timeout=timeout,
        verify=verify,
        proxy=proxy,
        follow_redirects=True,
        http2=False,
        limits=_KEEPALIVE_LIMITS,
    )


class _StablePostgrestClient(SyncPostgrestClient):
    def create_session(
        self,
        base_url: str,
        headers: dict,
        timeout,
        verify: bool = True,
        proxy: str | None = None,
    ) -> HTTPXClient:
        return _http_client(timeout=timeout, verify=verify, proxy=proxy)


class _StableSupabaseClient(SyncClient):
    """Supabase client with HTTP/2 disabled for auth and database calls."""

    @staticmethod
    def _init_supabase_auth_client(
        auth_url: str,
        client_options,
        verify: bool = True,
        proxy: str | None = None,
    ) -> SyncSupabaseAuthClient:
        return SyncSupabaseAuthClient(
            url=auth_url,
            auto_refresh_token=client_options.auto_refresh_token,
            persist_session=client_options.persist_session,
            storage=client_options.storage,
            headers=client_options.headers,
            flow_type=client_options.flow_type,
            verify=verify,
            proxy=proxy,
            http_client=_http_client(timeout=30, verify=verify, proxy=proxy),
        )

    @staticmethod
    def _init_postgrest_client(
        rest_url: str,
        headers: dict,
        schema: str,
        timeout=120,
        verify: bool = True,
        proxy: str | None = None,
    ) -> _StablePostgrestClient:
        return _StablePostgrestClient(
            rest_url,
            headers=headers,
            schema=schema,
            timeout=timeout,
            verify=verify,
            proxy=proxy,
        )


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required")
    return _StableSupabaseClient.create(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
