from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import UUID

from app.db import get_supabase

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Grant / keep Pro
_PRO_ON = {
    "initial_purchase",
    "renewal",
    "uncancellation",
    "non_renewing_purchase",
    "subscription_extended",
}

# Revoke Pro (access ended)
_PRO_OFF = {
    "expiration",
}


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
        "skipped": None,
    }

    if not user_id:
        result["skipped"] = "no_supabase_user_id"
        return result

    expires_ms = data.get("expirationAt")
    expires_iso = None
    if isinstance(expires_ms, (int, float)) and expires_ms > 0:
        expires_iso = datetime.fromtimestamp(expires_ms / 1000.0, tz=timezone.utc).isoformat()

    if event_name in _PRO_ON:
        is_pro = True
    elif event_name in _PRO_OFF:
        is_pro = False
        expires_iso = datetime.now(timezone.utc).isoformat()
    elif event_name in {"cancellation", "billing_issue", "subscription_paused", "product_change"}:
        # Access usually continues until expirationAt — keep is_pro, refresh expiry
        is_pro = True
    else:
        result["skipped"] = f"unhandled_event:{event_name}"
        return result

    sb = get_supabase()
    update = {"is_pro": is_pro, "pro_expires_at": expires_iso}
    res = sb.table("profiles").update(update).eq("id", str(user_id)).execute()
    if not res.data:
        # profile missing — upsert shell so webhook not lost
        sb.table("profiles").upsert(
            {"id": str(user_id), **update, "display_name": None}
        ).execute()

    result["updated"] = True
    result["is_pro"] = is_pro
    return result
