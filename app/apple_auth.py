from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx
import jwt
from jwt import PyJWKSet

from app.config import settings

_APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"


@dataclass(frozen=True)
class AppleIdentity:
    apple_sub: str
    email: str | None = None


def _normalize_apple_nonce(nonce: str) -> str:
    """iOS sets request.nonce = SHA256(raw) hex; Apple echoes that in the JWT claim."""
    value = (nonce or "").strip()
    if len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower()):
        return value.lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify_apple_identity_token(identity_token: str, *, nonce: str | None = None) -> AppleIdentity:
    if not settings.apple_bundle_id:
        raise ValueError("Apple bundle id is not configured")
    with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
        response = client.get(_APPLE_KEYS_URL)
        response.raise_for_status()
        jwks = response.json()
    header = jwt.get_unverified_header(identity_token)
    key_id = header.get("kid")
    key_set = PyJWKSet.from_dict(jwks)
    jwk = next((item for item in key_set.keys if item.key_id == key_id), None)
    if jwk is None:
        raise ValueError("Apple signing key not found")
    claims = jwt.decode(
        identity_token,
        key=jwk.key,
        algorithms=["RS256"],
        audience=settings.apple_bundle_id,
        issuer=_APPLE_ISSUER,
        options={"require": ["sub", "iss", "aud", "exp"]},
    )
    if nonce is not None:
        expected = _normalize_apple_nonce(nonce)
        claimed = str(claims.get("nonce") or "").strip().lower()
        if claimed != expected:
            raise ValueError("Invalid Apple nonce")
    return AppleIdentity(apple_sub=str(claims["sub"]), email=claims.get("email"))
