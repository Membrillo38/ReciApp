from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any, Iterable, Iterator

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from starlette.concurrency import run_in_threadpool

from app.config import settings


_pool: ConnectionPool | None = None
_pool_lock = Lock()
_db_actor: ContextVar[str] = ContextVar("reciapp_db_actor", default="")
_db_user_id: ContextVar[str] = ContextVar("reciapp_db_user_id", default="")


def _adapt(value: Any) -> Any:
    if isinstance(value, dict):
        return Jsonb(value)
    return value


def _params(params: Iterable[Any] | dict[str, Any] | None) -> Iterable[Any] | dict[str, Any] | None:
    if params is None:
        return None
    if isinstance(params, dict):
        return {key: _adapt(value) for key, value in params.items()}
    return tuple(_adapt(value) for value in params)


def get_pool() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            settings.validate_database()
            _pool = ConnectionPool(
                settings.database_url,
                min_size=1,
                max_size=10,
                open=True,
                kwargs={"row_factory": dict_row},
            )
        return _pool


@contextmanager
def db_context(*, actor: str, user_id: str = "") -> Iterator[None]:
    actor_token = _db_actor.set(actor)
    user_token = _db_user_id.set(user_id)
    try:
        yield
    finally:
        _db_actor.reset(actor_token)
        _db_user_id.reset(user_token)


def db_context_for_request(path: str, user_id: str | None) -> tuple[str, str]:
    """Map an HTTP path to RLS GUC values. Empty actor is fail-closed."""
    if path.startswith("/dashboard") or path.startswith("/v1/admin") or path.startswith("/v1/webhooks"):
        return "service", ""
    if path.startswith("/v1/auth/"):
        return "auth", user_id or ""
    if user_id:
        return "user", user_id
    return "", ""


@contextmanager
def get_conn():
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select set_config('app.actor', %s, true), set_config('app.user_id', %s, true)",
                (_db_actor.get(), _db_user_id.get()),
            )
        yield conn


def reset_db() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool = None


def fetch_one(sql: str, params: Iterable[Any] | dict[str, Any] | None = None) -> dict | None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _params(params))
            row = cur.fetchone()
            return dict(row) if row else None


def fetch_all(sql: str, params: Iterable[Any] | dict[str, Any] | None = None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _params(params))
            return [dict(row) for row in cur.fetchall()]


def execute(sql: str, params: Iterable[Any] | dict[str, Any] | None = None) -> int:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, _params(params))
            return cur.rowcount


def execute_returning(sql: str, params: Iterable[Any] | dict[str, Any] | None = None) -> dict | None:
    return fetch_one(sql, params)


async def probe_postgres() -> None:
    row = await run_in_threadpool(fetch_one, "select 1 as ok")
    if not row or row.get("ok") != 1:
        raise ValueError("Invalid readiness response")
