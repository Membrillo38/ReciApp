from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jwt import PyJWKSet

from app.config import settings

logger = logging.getLogger(__name__)

_APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"
_APPLE_TOKEN_URL = "https://appleid.apple.com/auth/token"
_APPLE_REVOKE_URL = "https://appleid.apple.com/auth/revoke"
_CLIENT_SECRET_TTL = timedelta(minutes=5)
_FERNET_SALT = b"reciapp-apple-provider-token-v1"
_FERNET_INFO = b"apple-refresh-token"


@dataclass(frozen=True)
class AppleIdentity:
    apple_sub: str
    email: str | None = None


def _apple_http() -> httpx.Client:
    return httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False)


def _normalize_apple_nonce(nonce: str) -> str:
    """iOS sets request.nonce = SHA256(raw) hex; Apple echoes that in the JWT claim."""
    value = (nonce or "").strip()
    if len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower()):
        return value.lower()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def apple_client_configured() -> bool:
    return bool(
        settings.apple_bundle_id
        and settings.apple_team_id
        and settings.apple_key_id
        and settings.apple_private_key
    )


def _apple_private_key_pem() -> str:
    raw = (settings.apple_private_key or "").strip()
    if "\\n" in raw and "\n" not in raw:
        raw = raw.replace("\\n", "\n")
    return raw


def create_apple_client_secret() -> str:
    if not apple_client_configured():
        raise ValueError("Apple client is not configured")
    now = datetime.now(timezone.utc)
    payload = {
        "iss": settings.apple_team_id,
        "iat": int(now.timestamp()),
        "exp": int((now + _CLIENT_SECRET_TTL).timestamp()),
        "aud": _APPLE_ISSUER,
        "sub": settings.apple_bundle_id,
    }
    try:
        return jwt.encode(
            payload,
            _apple_private_key_pem(),
            algorithm="ES256",
            headers={"kid": settings.apple_key_id},
        )
    except Exception as exc:
        raise ValueError("Apple client secret could not be created") from exc


def _fernet() -> Fernet:
    secret = (settings.apple_token_encryption_key or settings.auth_jwt_secret or "").encode("utf-8")
    if not secret:
        raise ValueError("Apple token encryption key is not configured")
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_FERNET_SALT,
        info=_FERNET_INFO,
    ).derive(secret)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_apple_refresh_token(raw: str) -> str:
    token = (raw or "").strip()
    if not token:
        raise ValueError("Apple refresh token is empty")
    return _fernet().encrypt(token.encode("utf-8")).decode("ascii")


def decrypt_apple_refresh_token(ciphertext: str) -> str:
    try:
        return _fernet().decrypt((ciphertext or "").encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError) as exc:
        raise ValueError("Apple refresh token could not be decrypted") from exc


def verify_apple_identity_token(identity_token: str, *, nonce: str | None = None) -> AppleIdentity:
    if not settings.apple_bundle_id:
        raise ValueError("Apple bundle id is not configured")
    with _apple_http() as client:
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


def exchange_apple_authorization_code(code: str, *, expected_sub: str) -> str | None:
    """Exchange a one-time Apple authorization code. Returns a refresh token or None."""
    authorization_code = (code or "").strip()
    if not authorization_code or not expected_sub or not apple_client_configured():
        return None
    try:
        client_secret = create_apple_client_secret()
        with _apple_http() as client:
            response = client.post(
                _APPLE_TOKEN_URL,
                data={
                    "client_id": settings.apple_bundle_id,
                    "client_secret": client_secret,
                    "code": authorization_code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            payload = response.json()
        refresh_token = str(payload.get("refresh_token") or "").strip()
        id_token = str(payload.get("id_token") or "").strip()
        if not refresh_token or not id_token:
            return None
        exchanged = verify_apple_identity_token(id_token)
        if exchanged.apple_sub != expected_sub:
            logger.warning("apple token subject mismatch")
            return None
        return refresh_token
    except Exception as exc:
        logger.warning("apple authorization code exchange failed error_type=%s", type(exc).__name__)
        return None


def revoke_apple_refresh_token(refresh_token: str) -> bool:
    """Revoke a stored Apple refresh token. True when Apple accepted or already invalidated."""
    token = (refresh_token or "").strip()
    if not token or not apple_client_configured():
        return False
    try:
        client_secret = create_apple_client_secret()
        with _apple_http() as client:
            response = client.post(
                _APPLE_REVOKE_URL,
                data={
                    "client_id": settings.apple_bundle_id,
                    "client_secret": client_secret,
                    "token": token,
                    "token_type_hint": "refresh_token",
                },
            )
        if response.status_code == 200:
            return True
        error_code = ""
        try:
            error_code = str((response.json() or {}).get("error") or "")
        except Exception:
            error_code = ""
        if response.status_code == 400 and error_code == "invalid_grant":
            return True
        logger.warning(
            "apple token revoke failed status=%s error_type=%s",
            response.status_code,
            error_code or "http_error",
        )
        return False
    except Exception as exc:
        logger.warning("apple token revoke failed error_type=%s", type(exc).__name__)
        return False
