from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from psycopg.errors import UniqueViolation

from app.config import settings
from app.db import execute_returning, fetch_one
from app.limits import (
    get_app_defaults,
    monthly_price_cents_from_superwall,
    period_price_cents_from_superwall,
    proceeds_cents_from_superwall,
)

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
    existing = fetch_one("select event_id, status from subscription_events where event_id = %s limit 1", (event_id,))
    if existing:
        return existing.get("status") not in {"processed", "skipped"}
    try:
        execute_returning(
            """
            insert into subscription_events (event_id, event_name, event_at, user_id, payload)
            values (%s, %s, %s, %s, %s)
            returning event_id
            """,
            (event_id, event_name[:120], event_at, user_id, _redacted(copy.deepcopy(payload))),
        )
    except UniqueViolation:
        # An insert conflict is not proof that the other delivery succeeded.
        existing = fetch_one("select status from subscription_events where event_id = %s limit 1", (event_id,))
        if not existing:
            raise
        return existing.get("status") not in {"processed", "skipped"}
    return True


def _mark_event(event_id: str, *, status: str, error: str | None = None) -> None:
    row = execute_returning(
        """
        update subscription_events
           set status = %s, error = %s, processed_at = %s
         where event_id = %s and status = any(%s)
        returning status
        """,
        (status, error[:500] if error else None, datetime.now(timezone.utc), event_id, ["received", "failed"]),
    )
    if not row:
        # Another delivery may have committed while this one was failing.
        # Terminal receipts are immutable, including processed versus skipped.
        current = fetch_one("select status from subscription_events where event_id = %s limit 1", (event_id,))
        if current and current.get("status") in {"processed", "skipped"}:
            return
        raise RuntimeError("Subscription event status was not persisted")


def apply_superwall_event(payload: dict, event_id: str | None = None) -> dict:
    if settings.maintenance_mode:
        raise HTTPException(status_code=503, detail="Maintenance in progress. Retry.", headers={"Retry-After": "30"})
    try:
        return _apply_superwall_event(payload, event_id)
    except (HTTPException, ValueError):
        raise
    except Exception:
        # A failed receipt must remain retryable, never become a successful replay.
        resolved = _event_id(payload, event_id)
        if resolved:
            try:
                _mark_event(resolved, status="failed", error="processing_failed")
            except Exception:
                pass
        raise HTTPException(status_code=503, detail="Subscription processing temporarily unavailable", headers={"Retry-After": "1"}) from None


def _apply_superwall_event(payload: dict, event_id: str | None = None) -> dict:
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
        profile_exists = fetch_one("select id, deleted_at from profiles where id = %s limit 1", (user_id,))
        if not profile_exists:
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

    current = fetch_one(
        "select subscription_event_at, subscription_event_id, deleted_at from profiles where id = %s limit 1",
        (user_id,),
    )
    if not current or current.get("deleted_at"):
        result["skipped"] = "profile_unavailable"
        _mark_event(resolved_event_id, status="skipped", error=result["skipped"])
        return result
    if current.get("subscription_event_id") == resolved_event_id:
        _mark_event(resolved_event_id, status="processed")
        result["skipped"] = "duplicate"
        return result
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
    period_price_cents = period_price_cents_from_superwall(data)
    monthly_price_cents = monthly_price_cents_from_superwall(data)
    proceeds_cents = proceeds_cents_from_superwall(data)
    update: dict = {
        "subscription_event_at": event_at.isoformat(),
        "subscription_event_id": resolved_event_id,
        "subscription_product_id": data.get("productId") or data.get("productIdentifier"),
        "subscription_currency": data.get("currency") or data.get("currencyCode"),
        "subscription_price_cents": period_price_cents,
    }
    if proceeds_cents:
        update["subscription_proceeds_cents"] = proceeds_cents

    now = datetime.now(timezone.utc)
    expired = False
    if expires_iso:
        try:
            expired = datetime.fromisoformat(expires_iso) <= now
        except ValueError:
            expired = False

    if event_name in _PRO_ON:
        update.update(
            {
                "is_pro": True,
                "pro_expires_at": expires_iso,
                "pro_monthly_price_cents": monthly_price_cents or defaults.default_pro_monthly_price_cents,
            }
        )
    elif event_name in _PRO_OFF:
        update.update(
            {
                "is_pro": False,
                "pro_expires_at": expires_iso or now.isoformat(),
                "pro_monthly_price_cents": None,
                "free_weekly_limit": defaults.free_weekly_limit,
            }
        )
    elif expired:
        # Cancellation / billing_issue / pause past expirationAt: revoke.
        update.update(
            {
                "is_pro": False,
                "pro_expires_at": expires_iso,
                "pro_monthly_price_cents": None,
                "free_weekly_limit": defaults.free_weekly_limit,
            }
        )
    else:
        # Still inside paid window (cancel-at-period-end, grace, pause).
        update.update({"is_pro": True, "pro_expires_at": expires_iso})
        if monthly_price_cents:
            update["pro_monthly_price_cents"] = monthly_price_cents

    # Compare-and-set prevents an old delivery from overwriting a concurrent
    # newer event. The deletion predicate also handles deletion after our read.
    assignments = ", ".join(f"{field} = %s" for field in update)
    res = execute_returning(
        f"""
        update profiles
           set {assignments}
         where id = %s
           and deleted_at is null
           and subscription_event_at is not distinct from %s
           and subscription_event_id is not distinct from %s
        returning id
        """,
        (*update.values(), user_id, current.get("subscription_event_at"), current.get("subscription_event_id")),
    )
    if not res:
        latest = fetch_one(
            "select subscription_event_at, subscription_event_id, deleted_at from profiles where id = %s limit 1",
            (user_id,),
        )
        if not latest or latest.get("deleted_at"):
            result["skipped"] = "profile_unavailable"
        elif latest.get("subscription_event_id") == resolved_event_id:
            _mark_event(resolved_event_id, status="processed")
            result["skipped"] = "duplicate"
            return result
        elif latest.get("subscription_event_at") and datetime.fromisoformat(str(latest["subscription_event_at"]).replace("Z", "+00:00")) > event_at:
            result["skipped"] = "out_of_order"
        else:
            raise RuntimeError("Subscription changed concurrently; retry event")
        _mark_event(resolved_event_id, status="skipped", error=result["skipped"])
        return result
    _mark_event(resolved_event_id, status="processed")

    result["updated"] = True
    result["is_pro"] = update.get("is_pro")
    result["pro_monthly_price_cents"] = update.get("pro_monthly_price_cents")
    return result
