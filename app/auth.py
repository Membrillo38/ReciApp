from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db import get_supabase

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    id: UUID
    email: str | None
    display_name: str | None
    is_pro: bool
    pro_expires_at: str | None


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        raise HTTPException(status_code=503, detail="API_KEY not configured")
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    try:
        sb = get_supabase()
        user_resp = sb.auth.get_user(creds.credentials)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    user = user_resp.user
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    uid = UUID(str(user.id))
    profile = (
        sb.table("profiles")
        .select("display_name,is_pro,pro_expires_at,deleted_at")
        .eq("id", str(uid))
        .limit(1)
        .execute()
    )
    row = (profile.data or [None])[0]
    if not row:
        # trigger may lag; upsert profile
        sb.table("profiles").upsert(
            {
                "id": str(uid),
                "display_name": user.email,
            }
        ).execute()
        row = {"display_name": user.email, "is_pro": False, "pro_expires_at": None, "deleted_at": None}

    if row.get("deleted_at"):
        raise HTTPException(status_code=403, detail="Account deleted")

    return AuthUser(
        id=uid,
        email=user.email,
        display_name=row.get("display_name"),
        is_pro=bool(row.get("is_pro")),
        pro_expires_at=row.get("pro_expires_at"),
    )
