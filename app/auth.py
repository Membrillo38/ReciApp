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

ACCOUNT_DELETED = "ACCOUNT_DELETED"
ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"


def account_error(code: str, message: str, status_code: int = 403) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


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


def _auth_user_from_row(uid: UUID, row: dict, claims_email: str | None) -> AuthUser:
    return AuthUser(
        id=uid,
        email=row.get("email") or claims_email,
        display_name=row.get("display_name"),
        is_pro=bool(row.get("is_pro")),
        pro_expires_at=str(row["pro_expires_at"]) if row.get("pro_expires_at") else None,
    )


def _load_profile(uid: UUID) -> dict | None:
    return fetch_one(
        """
        select id, email, display_name, is_pro, pro_expires_at, deleted_at
          from profiles
         where id = %s
         limit 1
        """,
        (uid,),
    )


def _bearer_claims(creds: HTTPAuthorizationCredentials | None) -> tuple[UUID, str | None]:
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
    email = claims.get("email")
    return uid, str(email) if email else None


def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    uid, claims_email = _bearer_claims(creds)
    try:
        row = _load_profile(uid)
    except Exception:
        raise HTTPException(status_code=503, detail="Authentication temporarily unavailable", headers={"Retry-After": "1"}) from None
    if not row:
        raise account_error(ACCOUNT_UNAVAILABLE, "Account unavailable")
    if row.get("deleted_at"):
        raise account_error(ACCOUNT_DELETED, "Account deleted")
    return _auth_user_from_row(uid, row, claims_email)


def current_user_allow_closed(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthUser:
    """JWT owner for DELETE /v1/me, including missing or already-closed profiles."""
    uid, claims_email = _bearer_claims(creds)
    try:
        row = _load_profile(uid)
    except Exception:
        raise HTTPException(status_code=503, detail="Authentication temporarily unavailable", headers={"Retry-After": "1"}) from None
    if not row or row.get("deleted_at"):
        return AuthUser(id=uid, email=None, display_name=None, is_pro=False, pro_expires_at=None)
    return _auth_user_from_row(uid, row, claims_email)
