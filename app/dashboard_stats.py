from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.limits import get_app_defaults
from app.db import get_supabase


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def dashboard_overview() -> dict:
    sb = get_supabase()
    day = _since(1)
    week = _since(7)
    month = _since(30)

    users = sb.table("profiles").select("id,is_pro,deleted_at").execute().data or []
    active_users = [u for u in users if not u.get("deleted_at")]
    pro_users = [u for u in active_users if u.get("is_pro")]

    recipes = sb.table("recipes").select("id", count="exact").execute()
    jobs_week = (
        sb.table("extract_jobs")
        .select("id,status,progress,cache_hit,cost_cents,created_at")
        .gte("created_at", week)
        .execute()
        .data
        or []
    )
    usage_month = (
        sb.table("usage_events")
        .select("kind,cost_cents,created_at,user_id")
        .gte("created_at", month)
        .execute()
        .data
        or []
    )
    reqs_day = (
        sb.table("api_request_logs")
        .select("id,path,status_code,duration_ms,created_at")
        .gte("created_at", day)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
        or []
    )
    reqs_week_count = (
        sb.table("api_request_logs")
        .select("id", count="exact")
        .gte("created_at", week)
        .execute()
    )
    spend_alerts = (
        sb.table("spend_alerts")
        .select("scope,threshold,period_start,created_at")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
        or []
    )

    cost_month = sum(float(u.get("cost_cents") or 0) for u in usage_month)
    cost_week = sum(
        float(u.get("cost_cents") or 0)
        for u in usage_month
        if (u.get("created_at") or "") >= week
    )
    hits = sum(1 for j in jobs_week if j.get("cache_hit"))
    misses = sum(1 for j in jobs_week if not j.get("cache_hit"))
    failed = sum(1 for j in jobs_week if j.get("status") == "failed")

    defaults = get_app_defaults()
    return {
        "users_total": len(active_users),
        "users_pro": len(pro_users),
        "users_free": len(active_users) - len(pro_users),
        "recipes_cached": int(recipes.count or 0),
        "jobs_week": len(jobs_week),
        "cache_hits_week": hits,
        "cache_misses_week": misses,
        "failed_week": failed,
        "cost_cents_week": round(cost_week, 4),
        "cost_cents_month": round(cost_month, 4),
        "cost_usd_week": round(cost_week / 100.0, 4),
        "cost_usd_month": round(cost_month / 100.0, 4),
        "requests_week": int(reqs_week_count.count or 0),
        "requests_recent": reqs_day[:50],
        "pro_price_cents": defaults.default_pro_monthly_price_cents,
        "pro_budget_cents": round(
            defaults.default_pro_monthly_price_cents * (1 - defaults.pro_margin_ratio),
            4,
        ),
        "margin_pct": int(defaults.pro_margin_ratio * 100),
        "spend_alerts": spend_alerts,
    }


def list_usage(limit: int = 100) -> list[dict]:
    sb = get_supabase()
    return (
        sb.table("usage_events")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )


def log_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    user_id: str | None,
    ip: str | None,
    correlation_id: str | None = None,
) -> None:
    if path.startswith("/dashboard") or path in {"/health", "/favicon.ico"}:
        return
    try:
        get_supabase().table("api_request_logs").insert(
            {
                "method": method,
                "path": path[:500],
                "status_code": status_code,
                "duration_ms": duration_ms,
                "user_id": user_id,
                "ip": (ip or "")[:64] or None,
                "correlation_id": correlation_id,
            }
        ).execute()
    except Exception:
        # Never break API if logging fails
        pass
