from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from app.config import settings
from app.db import fetch_one
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
    if not settings.auth_jwt_secret:
        raise HTTPException(status_code=503, detail="Authentication unavailable")

    try:
        claims = jwt.decode(
            creds.credentials,
            settings.auth_jwt_secret,
            algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
        )
        uid = UUID(str(claims.get("sub") or ""))
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token") from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid token") from None

    try:
        row = fetch_one(
            """
            select id, email, display_name, is_pro, pro_expires_at, deleted_at
              from profiles
             where id = %s
             limit 1
            """,
            (uid,),
        )
    except Exception:
        raise HTTPException(status_code=503, detail="Authentication temporarily unavailable", headers={"Retry-After": "1"}) from None
    if not row:
        raise HTTPException(status_code=403, detail="Account unavailable")
    if row.get("deleted_at"):
        raise HTTPException(status_code=403, detail="Account deleted")

    return AuthUser(
        id=uid,
        email=row.get("email") or claims.get("email"),
        display_name=row.get("display_name"),
        is_pro=bool(row.get("is_pro")),
        pro_expires_at=str(row["pro_expires_at"]) if row.get("pro_expires_at") else None,
    )
