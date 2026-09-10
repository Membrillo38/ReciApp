from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.limits import get_app_defaults
from app.db import execute, fetch_all, fetch_one


def dashboard_overview() -> dict:
    day = datetime.now(timezone.utc) - timedelta(days=1)
    week = datetime.now(timezone.utc) - timedelta(days=7)
    month = datetime.now(timezone.utc) - timedelta(days=30)

    users = fetch_all("select id, is_pro, deleted_at from profiles")
    active_users = [u for u in users if not u.get("deleted_at")]
    pro_users = [u for u in active_users if u.get("is_pro")]

    recipes = fetch_one("select count(*) as count from recipes") or {}
    jobs_week = fetch_all(
        "select id, status, progress, cache_hit, cost_cents, created_at from extract_jobs where created_at >= %s",
        (week,),
    )
    jobs_month = fetch_all(
        "select id, status, cost_cents, created_at, cache_hit from extract_jobs where created_at >= %s",
        (month,),
    )
    usage_month = fetch_all(
        "select kind, cost_cents, created_at, user_id from usage_events where created_at >= %s",
        (month,),
    )
    reqs_day = fetch_all(
        """
        select id, path, status_code, duration_ms, created_at
          from api_request_logs
         where created_at >= %s
         order by created_at desc
         limit 200
        """,
        (day,),
    )
    reqs_week_count = fetch_one("select count(*) as count from api_request_logs where created_at >= %s", (week,)) or {}
    spend_alerts = fetch_all(
        "select scope, threshold, period_start, created_at from spend_alerts order by created_at desc limit 20"
    )

    # Real OpenAI spend: sum job cost_cents for completed + failed (includes paid failures).
    cost_month = sum(
        float(j.get("cost_cents") or 0)
        for j in jobs_month
        if j.get("status") in {"completed", "failed"}
    )
    cost_week = sum(
        float(j.get("cost_cents") or 0)
        for j in jobs_week
        if j.get("status") in {"completed", "failed"}
    )
    hits = sum(1 for j in jobs_week if j.get("cache_hit"))
    misses = sum(1 for j in jobs_week if not j.get("cache_hit"))
    failed = sum(1 for j in jobs_week if j.get("status") == "failed")

    live = fetch_all(
        "select id, status from extract_jobs where job_kind = 'extract' and status = any(%s)",
        (["pending", "processing"],),
    )
    processing_now = sum(1 for j in live if j.get("status") == "processing")
    queued_now = sum(1 for j in live if j.get("status") == "pending")

    defaults = get_app_defaults()
    return {
        "users_total": len(active_users),
        "users_pro": len(pro_users),
        "users_free": len(active_users) - len(pro_users),
        "recipes_cached": int(recipes.get("count") or 0),
        "jobs_week": len(jobs_week),
        "cache_hits_week": hits,
        "cache_misses_week": misses,
        "failed_week": failed,
        "processing_now": processing_now,
        "queued_now": queued_now,
        "cost_cents_week": round(cost_week, 4),
        "cost_cents_month": round(cost_month, 4),
        "cost_usd_week": round(cost_week / 100.0, 4),
        "cost_usd_month": round(cost_month / 100.0, 4),
        "usage_events_month": len(usage_month),
        "requests_week": int(reqs_week_count.get("count") or 0),
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
    return fetch_all("select * from usage_events order by created_at desc limit %s", (limit,))


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
        execute(
            """
            insert into api_request_logs (method, path, status_code, duration_ms, user_id, ip, correlation_id)
            values (%s, %s, %s, %s, %s, %s, %s)
            """,
            (method, path[:500], status_code, duration_ms, user_id, (ip or "")[:64] or None, correlation_id),
        )
    except Exception:
        # Never break API if logging fails
        pass
