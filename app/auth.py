from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from supabase_auth.errors import AuthApiError, AuthInvalidCredentialsError, AuthInvalidJwtError, AuthSessionMissingError

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings
from app.db import get_supabase
from app.security import audit_security_event, safe_compare

_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    id: UUID
    email: str | None
    display_name: str | None
    is_pro: bool
    pro_expires_at: str | None


def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        audit_security_event(event="admin_api_key_unconfigured", request=request)
        raise HTTPException(status_code=503, detail="API_KEY not configured")
    if not safe_compare(x_api_key, settings.api_key):
        audit_security_event(event="admin_api_key_rejected", request=request)
        raise HTTPException(status_code=401, detail="Invalid API key")
    audit_security_event(event="admin_api_key_accepted", request=request)


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    try:
        sb = get_supabase()
        user_resp = sb.auth.get_user(creds.credentials)
    except (AuthInvalidCredentialsError, AuthInvalidJwtError, AuthSessionMissingError):
        raise HTTPException(status_code=401, detail="Invalid token") from None
    except AuthApiError as exc:
        if exc.status in {400, 401, 403, 404, 422}:
            raise HTTPException(status_code=401, detail="Invalid token") from None
        raise HTTPException(status_code=503, detail="Authentication temporarily unavailable", headers={"Retry-After": "1"}) from None
    except Exception:
        raise HTTPException(status_code=503, detail="Authentication temporarily unavailable", headers={"Retry-After": "1"}) from None

    user = user_resp.user
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")

    uid = UUID(str(user.id))
    try:
        profile = (
            sb.table("profiles")
            .select("display_name,is_pro,pro_expires_at,deleted_at")
            .eq("id", str(uid))
            .limit(1)
            .execute()
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Account temporarily unavailable", headers={"Retry-After": "1"}) from None
    row = (profile.data or [None])[0]
    if not row:
        raise HTTPException(status_code=403, detail="Account unavailable")

    if row.get("deleted_at"):
        raise HTTPException(status_code=403, detail="Account deleted")

    return AuthUser(
        id=uid,
        email=user.email,
        display_name=row.get("display_name"),
        is_pro=bool(row.get("is_pro")),
        pro_expires_at=row.get("pro_expires_at"),
    )
