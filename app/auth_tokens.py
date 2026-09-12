from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

from app.config import settings
from app.db import execute, execute_returning, fetch_one


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_access_token(user_id: UUID, email: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.auth_access_token_ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, settings.auth_jwt_secret, algorithm="HS256")


def create_refresh_token(user_id: UUID, *, user_agent: str | None = None, ip_hash: str | None = None) -> str:
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_refresh_token_ttl_seconds)
    execute(
        """
        insert into auth_refresh_tokens (user_id, token_hash, expires_at, user_agent, ip_hash)
        values (%s, %s, %s, %s, %s)
        """,
        (user_id, _hash(raw), expires_at, (user_agent or "")[:300] or None, ip_hash),
    )
    return raw


def rotate_refresh_token(raw: str) -> dict | None:
    row = fetch_one(
        """
        select t.id, t.user_id, p.email
          from auth_refresh_tokens t
          join profiles p on p.id = t.user_id
         where t.token_hash = %s
           and t.revoked_at is null
           and t.expires_at > now()
           and p.deleted_at is null
         limit 1
        """,
        (_hash(raw),),
    )
    if not row:
        return None
    new_refresh = secrets.token_urlsafe(48)
    new_hash = _hash(new_refresh)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_refresh_token_ttl_seconds)
    updated = execute_returning(
        """
        update auth_refresh_tokens
           set revoked_at = now()
         where id = %s
           and revoked_at is null
        returning id
        """,
        (row["id"],),
    )
    if not updated:
        return None
    execute(
        """
        insert into auth_refresh_tokens (user_id, token_hash, expires_at)
        values (%s, %s, %s)
        """,
        (row["user_id"], new_hash, expires_at),
    )
    return {
        "access_token": create_access_token(UUID(str(row["user_id"])), row.get("email")),
        "refresh_token": new_refresh,
    }


def revoke_refresh_token(raw: str) -> None:
    if not raw:
        return
    execute(
        """
        update auth_refresh_tokens
           set revoked_at = now()
         where token_hash = %s
           and revoked_at is null
        """,
        (_hash(raw),),
    )


def revoke_all_refresh_tokens(user_id: UUID) -> None:
    execute(
        """
        update auth_refresh_tokens
           set revoked_at = now()
         where user_id = %s
           and revoked_at is null
        """,
        (user_id,),
    )
