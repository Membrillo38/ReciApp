from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.limits import get_app_defaults
from app.db import execute, fetch_all, fetch_one


def _job_cost_since(since) -> float:
    row = fetch_one(
        """
        select coalesce(sum(cost_cents), 0) as total
          from extract_jobs
         where created_at >= %s
           and status = any(%s)
        """,
        (since, ["completed", "failed"]),
    ) or {}
    return float(row.get("total") or 0)


def _job_cost_total() -> float:
    row = fetch_one(
        """
        select coalesce(sum(cost_cents), 0) as total
          from extract_jobs
         where status = any(%s)
        """,
        (["completed", "failed"],),
    ) or {}
    return float(row.get("total") or 0)


def _request_stats(since) -> dict:
    counts = fetch_all(
        """
        select status_code, count(*)::int as count
          from api_request_logs
         where created_at >= %s
         group by status_code
         order by status_code
        """,
        (since,),
    )
    latency = fetch_one(
        """
        select
          count(*)::int as count,
          coalesce(round(avg(duration_ms)), 0)::int as avg_ms,
          coalesce(round(percentile_cont(0.5) within group (order by duration_ms)), 0)::int as p50_ms,
          coalesce(round(percentile_cont(0.95) within group (order by duration_ms)), 0)::int as p95_ms,
          coalesce(max(duration_ms), 0)::int as max_ms
          from api_request_logs
         where created_at >= %s
        """,
        (since,),
    ) or {}
    by_status = {int(r["status_code"]): int(r["count"]) for r in counts}
    total = int(latency.get("count") or 0)
    return {
        "total": total,
        "by_status": by_status,
        "ok_2xx": sum(c for code, c in by_status.items() if 200 <= code < 300),
        "err_4xx": sum(c for code, c in by_status.items() if 400 <= code < 500),
        "err_5xx": sum(c for code, c in by_status.items() if 500 <= code < 600),
        "status_200": by_status.get(200, 0),
        "status_503": by_status.get(503, 0),
        "avg_ms": int(latency.get("avg_ms") or 0),
        "p50_ms": int(latency.get("p50_ms") or 0),
        "p95_ms": int(latency.get("p95_ms") or 0),
        "max_ms": int(latency.get("max_ms") or 0),
    }


def _postgres_footprint() -> dict:
    empty = {
        "db_name": "",
        "db_size_pretty": "—",
        "db_size_bytes": 0,
        "app_size_pretty": "—",
        "app_size_bytes": 0,
        "catalog_size_pretty": "—",
        "catalog_size_bytes": 0,
        "cluster_size_pretty": "—",
        "cluster_size_bytes": 0,
        "tables": [],
    }
    try:
        size = fetch_one(
            """
            with app as (
              select coalesce(sum(pg_total_relation_size(c.oid)), 0)::bigint as app_bytes
                from pg_class c
                join pg_namespace n on n.oid = c.relnamespace
               where n.nspname not in ('pg_catalog', 'information_schema', 'pg_toast')
                 and c.relkind in ('r', 'm', 'p')
            )
            select
              current_database() as db_name,
              pg_size_pretty(pg_database_size(current_database())) as db_pretty,
              pg_database_size(current_database())::bigint as db_bytes,
              pg_size_pretty(app.app_bytes) as app_pretty,
              app.app_bytes,
              pg_size_pretty(pg_database_size(current_database()) - app.app_bytes) as catalog_pretty,
              (pg_database_size(current_database()) - app.app_bytes)::bigint as catalog_bytes,
              (
                select pg_size_pretty(sum(pg_database_size(datname)))
                  from pg_database
                 where datistemplate = false
              ) as cluster_pretty,
              (
                select sum(pg_database_size(datname))::bigint
                  from pg_database
                 where datistemplate = false
              ) as cluster_bytes
              from app
            """
        ) or {}
        tables = fetch_all(
            """
            select
              n.nspname || '.' || c.relname as name,
              pg_size_pretty(pg_total_relation_size(c.oid)) as pretty,
              pg_total_relation_size(c.oid)::bigint as bytes
              from pg_class c
              join pg_namespace n on n.oid = c.relnamespace
             where n.nspname not in ('pg_catalog', 'information_schema')
               and c.relkind in ('r', 'm', 'p')
             order by pg_total_relation_size(c.oid) desc
             limit 12
            """
        )
    except Exception:
        return empty
    db_bytes = int(size.get("db_bytes") or 0)
    app_bytes = int(size.get("app_bytes") or 0)
    catalog_bytes = int(size.get("catalog_bytes") or 0)
    if catalog_bytes < 0:
        catalog_bytes = 0
    return {
        "db_name": str(size.get("db_name") or ""),
        "db_size_pretty": str(size.get("db_pretty") or "—"),
        "db_size_bytes": db_bytes,
        "app_size_pretty": str(size.get("app_pretty") or "—"),
        "app_size_bytes": app_bytes,
        "catalog_size_pretty": str(size.get("catalog_pretty") or "—"),
        "catalog_size_bytes": catalog_bytes,
        "cluster_size_pretty": str(size.get("cluster_pretty") or "—"),
        "cluster_size_bytes": int(size.get("cluster_bytes") or 0),
        "tables": tables,
    }


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
    usage_month = fetch_all(
        "select kind, cost_cents, created_at, user_id from usage_events where created_at >= %s",
        (month,),
    )
    reqs_day = fetch_all(
        """
        select id, method, path, status_code, duration_ms, created_at
          from api_request_logs
         where created_at >= %s
         order by created_at desc
         limit 200
        """,
        (day,),
    )
    spend_alerts = fetch_all(
        "select scope, threshold, period_start, created_at from spend_alerts order by created_at desc limit 20"
    )

    cost_day = _job_cost_since(day)
    cost_week = _job_cost_since(week)
    cost_month = _job_cost_since(month)
    cost_total = _job_cost_total()

    hits = sum(1 for j in jobs_week if j.get("cache_hit"))
    misses = sum(1 for j in jobs_week if not j.get("cache_hit"))
    failed = sum(1 for j in jobs_week if j.get("status") == "failed")

    live = fetch_all(
        "select id, status from extract_jobs where job_kind = 'extract' and status = any(%s)",
        (["pending", "processing"],),
    )
    processing_now = sum(1 for j in live if j.get("status") == "processing")
    queued_now = sum(1 for j in live if j.get("status") == "pending")

    api_day = _request_stats(day)
    api_week = _request_stats(week)
    api_month = _request_stats(month)

    defaults = get_app_defaults()
    pg = _postgres_footprint()
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
        "cost_cents_day": round(cost_day, 4),
        "cost_cents_week": round(cost_week, 4),
        "cost_cents_month": round(cost_month, 4),
        "cost_cents_total": round(cost_total, 4),
        "cost_usd_day": round(cost_day / 100.0, 4),
        "cost_usd_week": round(cost_week / 100.0, 4),
        "cost_usd_month": round(cost_month / 100.0, 4),
        "cost_usd_total": round(cost_total / 100.0, 4),
        "usage_events_month": len(usage_month),
        "requests_day": api_day["total"],
        "requests_week": api_week["total"],
        "requests_month": api_month["total"],
        "api_day": api_day,
        "api_week": api_week,
        "api_month": api_month,
        "requests_recent": reqs_day[:50],
        "pro_price_cents": defaults.default_pro_monthly_price_cents,
        "pro_budget_cents": round(
            defaults.default_pro_monthly_price_cents * (1 - defaults.pro_margin_ratio),
            4,
        ),
        "margin_pct": int(defaults.pro_margin_ratio * 100),
        "spend_alerts": spend_alerts,
        **pg,
    }


def list_usage(limit: int = 100) -> list[dict]:
    return fetch_all("select * from usage_events order by created_at desc limit %s", (limit,))


def dashboard_threats() -> dict:
    snapshot_row = fetch_one(
        """
        select metadata, created_at
          from security_events
         where event = 'fail2ban_snapshot'
         order by created_at desc
         limit 1
        """
    ) or {}
    snapshot = snapshot_row.get("metadata") or {}
    if not isinstance(snapshot, dict):
        snapshot = {}
    jails = snapshot.get("jails") if isinstance(snapshot.get("jails"), dict) else {}
    banned: list[dict] = []
    seen: set[str] = set()
    currently_banned = 0
    currently_failed = 0
    total_banned = 0
    total_failed = 0
    for name, jail in jails.items():
        if not isinstance(jail, dict):
            continue
        currently_banned += int(jail.get("currently_banned") or 0)
        currently_failed += int(jail.get("currently_failed") or 0)
        total_banned += int(jail.get("total_banned") or 0)
        total_failed += int(jail.get("total_failed") or 0)
        for ip in jail.get("banned_ips") or []:
            text = str(ip).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            banned.append({"ip": text, "jail": name})
    events = fetch_all(
        """
        select created_at, event, ip, metadata
          from security_events
         where event = 'scanner_probe'
         order by created_at desc
         limit 150
        """
    )
    ssh_recent = snapshot.get("ssh_recent") if isinstance(snapshot.get("ssh_recent"), list) else []
    return {
        "snapshot_at": snapshot_row.get("created_at"),
        "currently_banned": currently_banned,
        "currently_failed": currently_failed,
        "total_banned": total_banned,
        "total_failed": total_failed,
        "jails": jails,
        "banned": banned,
        "ssh_recent": ssh_recent[:60],
        "events": events,
    }


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
