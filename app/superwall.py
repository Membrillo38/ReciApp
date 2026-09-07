from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from uuid import UUID

from app.config import settings
from app.db import get_supabase
from app.limits import get_app_defaults, price_cents_from_superwall, proceeds_cents_from_superwall

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_PRO_ON = {
    "initial_purchase", "renewal", "uncancellation", "non_renewing_purchase", "subscription_extended"
}
_PRO_OFF = {
    "expiration", "refund", "refunded", "subscription_refunded", "revocation", "revoked"
}
_PRO_STAYS_ON = {"cancellation", "billing_issue", "subscription_paused", "product_change"}
_SENSITIVE_KEYS = {"authorization", "access_token", "id_token", "password", "secret", "signature", "api_key", "apikey"}


def extract_supabase_user_id(payload: dict) -> UUID | None:
    data = payload.get("data") or {}
    candidates: list[str] = []
    attrs = data.get("userAttributes") or payload.get("userAttributes") or {}
    if isinstance(attrs, dict):
        for key in ("supabase_user_id", "user_id", "supabaseUserId", "userId"):
            if attrs.get(key):
                candidates.append(str(attrs[key]))
    for key in ("originalAppUserId", "appUserId", "appAccountToken"):
        if data.get(key) or payload.get(key):
            candidates.append(str(data.get(key) or payload.get(key)))
    for raw in candidates:
        cleaned = raw[5:] if raw.startswith("user_") else raw
        if cleaned.startswith("$SuperwallAlias:"):
            continue
        if _UUID_RE.match(cleaned):
            return UUID(cleaned)
    return None


def _event_id(payload: dict, supplied: str | None) -> str | None:
    data = payload.get("data") or {}
    for value in (payload.get("id"), payload.get("eventId"), data.get("id"), data.get("eventId"), supplied):
        if value:
            return str(value)[:240]
    return None


def _event_datetime(payload: dict) -> datetime:
    data = payload.get("data") or {}
    value = next(
        (item for item in (
            payload.get("createdAt"), payload.get("eventTimestamp"), payload.get("timestamp"),
            data.get("createdAt"), data.get("eventTimestamp"), data.get("timestamp"),
        ) if item is not None),
        None,
    )
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value) / (1000 if value > 10_000_000_000 else 1), tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _redacted(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower().replace("-", "_") in _SENSITIVE_KEYS else _redacted(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redacted(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:4000]
    return value


def _record_event(event_id: str, event_name: str, event_at: datetime, user_id: UUID | None, payload: dict) -> bool:
    sb = get_supabase()
    existing = sb.table("subscription_events").select("event_id,status").eq("event_id", event_id).limit(1).execute()
    if existing.data:
        return False
    try:
        sb.table("subscription_events").insert({
            "event_id": event_id,
            "event_name": event_name[:120],
            "event_at": event_at.isoformat(),
            "user_id": str(user_id) if user_id else None,
            "payload": _redacted(copy.deepcopy(payload)),
        }).execute()
    except Exception as exc:
        # Svix may retry concurrently; the primary key is the idempotency gate.
        if "23505" in str(exc) and "event_id" in str(exc):
            return False
        raise
    return True


def _mark_event(event_id: str, *, status: str, error: str | None = None) -> None:
    try:
        get_supabase().table("subscription_events").update({
            "status": status,
            "error": error[:500] if error else None,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("event_id", event_id).execute()
    except Exception:
        pass


def apply_superwall_event(payload: dict, event_id: str | None = None) -> dict:
    data = payload.get("data") or {}
    event_name = str(data.get("name") or payload.get("type") or "").lower()
    resolved_event_id = _event_id(payload, event_id)
    if not resolved_event_id:
        raise ValueError("Webhook event id required")
    event_at = _event_datetime(payload)
    user_id = extract_supabase_user_id(payload)
    result = {
        "event": event_name,
        "user_id": str(user_id) if user_id else None,
        "updated": False,
        "is_pro": None,
        "pro_monthly_price_cents": None,
        "skipped": None,
    }

    event_user_id = user_id
    if user_id:
        profile_exists = get_supabase().table("profiles").select("id").eq("id", str(user_id)).limit(1).execute()
        if not profile_exists.data:
            event_user_id = None
    if not _record_event(resolved_event_id, event_name, event_at, event_user_id, payload):
        result["skipped"] = "duplicate"
        return result

    age = (datetime.now(timezone.utc) - event_at).total_seconds()
    if age > settings.webhook_max_age_seconds or age < -300:
        _mark_event(resolved_event_id, status="skipped", error="stale_event")
        result["skipped"] = "stale_event"
        return result
    if not user_id:
        _mark_event(resolved_event_id, status="skipped", error="no_supabase_user_id")
        result["skipped"] = "no_supabase_user_id"
        return result
    if event_name not in _PRO_ON and event_name not in _PRO_OFF and event_name not in _PRO_STAYS_ON:
        _mark_event(resolved_event_id, status="skipped", error=f"unhandled_event:{event_name}")
        result["skipped"] = f"unhandled_event:{event_name}"
        return result

    sb = get_supabase()
    profile = sb.table("profiles").select("subscription_event_at,subscription_event_id").eq("id", str(user_id)).limit(1).execute()
    current = (profile.data or [{}])[0]
    if current.get("subscription_event_at"):
        try:
            current_at = datetime.fromisoformat(str(current["subscription_event_at"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            if current_at > event_at:
                _mark_event(resolved_event_id, status="skipped", error="out_of_order")
                result["skipped"] = "out_of_order"
                return result
        except ValueError:
            pass

    expires_ms = data.get("expirationAt")
    expires_iso = None
    if isinstance(expires_ms, (int, float)) and expires_ms > 0:
        expires_iso = datetime.fromtimestamp(expires_ms / 1000.0, tz=timezone.utc).isoformat()
    defaults = get_app_defaults()
    price_cents = price_cents_from_superwall(data)
    proceeds_cents = proceeds_cents_from_superwall(data)
    update: dict = {
        "subscription_event_at": event_at.isoformat(),
        "subscription_event_id": resolved_event_id,
        "subscription_product_id": data.get("productId") or data.get("productIdentifier"),
        "subscription_currency": data.get("currency") or data.get("currencyCode"),
        "subscription_price_cents": price_cents,
    }
    if proceeds_cents:
        update["subscription_proceeds_cents"] = proceeds_cents

    if event_name in _PRO_ON:
        update.update({"is_pro": True, "pro_expires_at": expires_iso, "pro_monthly_price_cents": price_cents or defaults.default_pro_monthly_price_cents})
    elif event_name in _PRO_OFF:
        update.update({"is_pro": False, "pro_expires_at": expires_iso or datetime.now(timezone.utc).isoformat(), "pro_monthly_price_cents": None, "free_weekly_limit": defaults.free_weekly_limit})
    else:
        # Cancellation, billing issue and pause retain access until expiry.
        update.update({"is_pro": True, "pro_expires_at": expires_iso})
        if price_cents:
            update["pro_monthly_price_cents"] = price_cents

    try:
        res = sb.table("profiles").update(update).eq("id", str(user_id)).execute()
        if not res.data:
            sb.table("profiles").upsert({"id": str(user_id), **update, "display_name": None}).execute()
        _mark_event(resolved_event_id, status="processed")
    except Exception as exc:
        _mark_event(
            resolved_event_id,
            status="failed",
            error=f"processing_failed:{type(exc).__name__}",
        )
        raise

    result["updated"] = True
    result["is_pro"] = update.get("is_pro")
    result["pro_monthly_price_cents"] = update.get("pro_monthly_price_cents")
    return result
