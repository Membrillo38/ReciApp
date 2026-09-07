from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from app.config import settings
from app.db import get_supabase


def _b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _verify_signature(public_key, signature: bytes, message: bytes, algorithm) -> None:
    from cryptography.hazmat.primitives import asymmetric, hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding

    if isinstance(public_key, asymmetric.rsa.RSAPublicKey):
        public_key.verify(signature, message, padding.PKCS1v15(), algorithm)
    elif isinstance(public_key, ec.EllipticCurvePublicKey):
        public_key.verify(signature, message, ec.ECDSA(algorithm))
    else:
        raise ValueError("Unsupported Apple certificate key")


def verify_jws(compact: str) -> dict:
    """Verify Apple JWS signature and certificate chain; never trust plain JSON."""
    if compact.count(".") != 2 or not settings.apple_root_ca_pem:
        raise ValueError("Apple JWS verification is not configured")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
    except ImportError as exc:
        raise ValueError("Apple JWS verification dependency unavailable") from exc

    encoded_header, encoded_payload, encoded_signature = compact.split(".")
    header = json.loads(_b64(encoded_header))
    payload = json.loads(_b64(encoded_payload))
    if header.get("alg") != "ES256" or not header.get("x5c"):
        raise ValueError("Unsupported Apple JWS")

    chain = [x509.load_der_x509_certificate(base64.b64decode(value)) for value in header["x5c"]]
    root = x509.load_pem_x509_certificate(settings.apple_root_ca_pem.encode("utf-8"))
    if chain[-1].fingerprint(hashes.SHA256()) != root.fingerprint(hashes.SHA256()):
        # Apple may omit the root from x5c; verify the final intermediate against
        # the configured root instead of accepting an arbitrary CA.
        _verify_signature(root.public_key(), chain[-1].signature, chain[-1].tbs_certificate_bytes, chain[-1].signature_hash_algorithm)
    for child, issuer in zip(chain, chain[1:]):
        _verify_signature(issuer.public_key(), child.signature, child.tbs_certificate_bytes, child.signature_hash_algorithm)
    _verify_signature(chain[0].public_key(), _b64(encoded_signature), f"{encoded_header}.{encoded_payload}".encode("ascii"), hashes.SHA256())
    return payload


def process_signed_notification(signed_payload: str) -> dict:
    notification = verify_jws(signed_payload)
    notification_id = str(notification.get("notificationUUID") or "")
    if not notification_id:
        raise ValueError("Apple notification id required")
    data = notification.get("data") or {}
    if data.get("bundleId") and data["bundleId"] != settings.apple_bundle_id:
        return {"ok": True, "skipped": "wrong_bundle"}
    if data.get("environment") and data["environment"] != settings.apple_environment:
        return {"ok": True, "skipped": "wrong_environment"}

    sb = get_supabase()
    existing = sb.table("apple_notification_events").select("event_id").eq("event_id", notification_id).limit(1).execute()
    if existing.data:
        return {"ok": True, "skipped": "duplicate", "event_id": notification_id}

    transaction = {}
    if data.get("signedTransactionInfo"):
        transaction = verify_jws(data["signedTransactionInfo"])
    user_id = transaction.get("appAccountToken")
    try:
        user_uuid = UUID(str(user_id))
    except (ValueError, TypeError):
        user_uuid = None

    event_type = str(notification.get("notificationType") or "").upper()
    expiry_ms = transaction.get("expiresDate")
    expires_at = None
    if isinstance(expiry_ms, (int, float)):
        expires_at = datetime.fromtimestamp(float(expiry_ms) / 1000, tz=timezone.utc)
    off = event_type in {"EXPIRED", "REFUND", "REVOKE"} or bool(transaction.get("revocationDate"))
    update = {"is_pro": not off, "pro_expires_at": expires_at.isoformat() if expires_at else None}
    if user_uuid:
        changed = sb.table("profiles").update(update).eq("id", str(user_uuid)).execute()
        if not changed.data:
            sb.table("profiles").upsert({"id": str(user_uuid), "display_name": None, **update}).execute()

    redacted = {"notificationType": event_type, "environment": data.get("environment"), "productId": transaction.get("productId")}
    sb.table("apple_notification_events").insert({
        "event_id": notification_id,
        "notification_type": event_type,
        "signed_payload_sha256": hashlib.sha256(signed_payload.encode()).hexdigest(),
        "payload": redacted,
        "status": "processed" if user_uuid else "skipped",
    }).execute()
    return {"ok": True, "event_id": notification_id, "updated": bool(user_uuid), "is_pro": update["is_pro"] if user_uuid else None}
