from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from app.db import get_supabase
from app.limits import get_app_defaults, price_cents_from_superwall

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_PRO_ON = {
    "initial_purchase",
    "renewal",
    "uncancellation",
    "non_renewing_purchase",
    "subscription_extended",
}

_PRO_OFF = {"expiration"}


def extract_supabase_user_id(payload: dict) -> UUID | None:
    data = payload.get("data") or {}
    candidates: list[str] = []

    attrs = data.get("userAttributes") or payload.get("userAttributes") or {}
    if isinstance(attrs, dict):
        for key in ("supabase_user_id", "user_id", "supabaseUserId", "userId"):
            val = attrs.get(key)
            if val:
                candidates.append(str(val))

    for key in ("originalAppUserId", "appUserId"):
        val = data.get(key)
        if val:
            candidates.append(str(val))

    for raw in candidates:
        cleaned = raw
        if cleaned.startswith("$SuperwallAlias:"):
            continue
        if cleaned.startswith("user_"):
            cleaned = cleaned[5:]
        if _UUID_RE.match(cleaned):
            return UUID(cleaned)
    return None


def apply_superwall_event(payload: dict) -> dict:
    data = payload.get("data") or {}
    event_name = str(data.get("name") or payload.get("type") or "").lower()
    user_id = extract_supabase_user_id(payload)

    result = {
        "event": event_name,
        "user_id": str(user_id) if user_id else None,
        "updated": False,
        "is_pro": None,
        "pro_monthly_price_cents": None,
        "skipped": None,
    }

    if not user_id:
        result["skipped"] = "no_supabase_user_id"
        return result

    expires_ms = data.get("expirationAt")
    expires_iso = None
    if isinstance(expires_ms, (int, float)) and expires_ms > 0:
        expires_iso = datetime.fromtimestamp(expires_ms / 1000.0, tz=timezone.utc).isoformat()

    defaults = get_app_defaults()
    update: dict = {}

    if event_name in _PRO_ON:
        update["is_pro"] = True
        update["pro_expires_at"] = expires_iso
        price_cents = price_cents_from_superwall(data)
        if price_cents:
            update["pro_monthly_price_cents"] = price_cents
        elif event_name == "initial_purchase":
            update["pro_monthly_price_cents"] = defaults.default_pro_monthly_price_cents
    elif event_name in _PRO_OFF:
        update["is_pro"] = False
        update["pro_expires_at"] = expires_iso or datetime.now(timezone.utc).isoformat()
        update["pro_monthly_price_cents"] = None
        update["free_weekly_limit"] = defaults.free_weekly_limit
    elif event_name in {"cancellation", "billing_issue", "subscription_paused", "product_change"}:
        update["is_pro"] = True
        update["pro_expires_at"] = expires_iso
        price_cents = price_cents_from_superwall(data)
        if price_cents:
            update["pro_monthly_price_cents"] = price_cents
    else:
        result["skipped"] = f"unhandled_event:{event_name}"
        return result

    sb = get_supabase()
    res = sb.table("profiles").update(update).eq("id", str(user_id)).execute()
    if not res.data:
        sb.table("profiles").upsert({"id": str(user_id), **update, "display_name": None}).execute()

    result["updated"] = True
    result["is_pro"] = update.get("is_pro")
    result["pro_monthly_price_cents"] = update.get("pro_monthly_price_cents")
    return result
