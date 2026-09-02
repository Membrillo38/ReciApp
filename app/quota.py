from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from app.auth import AuthUser
from app.db import get_supabase
from app.limits import resolve_user_limits
from app.store import week_start_utc


@dataclass
class QuotaStatus:
    is_pro: bool
    free_used_this_week: int
    free_limit: int
    free_remaining: int
    pro_cost_cents_this_month: float
    pro_budget_cents: float
    pro_remaining_cents: float
    pro_monthly_price_cents: int


def _month_start_utc(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_quota(user: AuthUser) -> QuotaStatus:
    sb = get_supabase()
    week_start = week_start_utc().isoformat()
    month_start = _month_start_utc().isoformat()

    profile = (
        sb.table("profiles")
        .select("free_weekly_limit,pro_monthly_price_cents,pro_margin_ratio,is_pro")
        .eq("id", str(user.id))
        .limit(1)
        .execute()
    )
    row = (profile.data or [{}])[0]
    limits = resolve_user_limits(row)

    week = (
        sb.table("usage_events")
        .select("id", count="exact")
        .eq("user_id", str(user.id))
        .gte("created_at", week_start)
        .execute()
    )
    free_used = int(week.count or 0)

    month = (
        sb.table("usage_events")
        .select("cost_cents")
        .eq("user_id", str(user.id))
        .eq("kind", "extract_miss")
        .gte("created_at", month_start)
        .execute()
    )
    pro_cost = sum(float(r.get("cost_cents") or 0) for r in (month.data or []))

    return QuotaStatus(
        is_pro=user.is_pro,
        free_used_this_week=free_used,
        free_limit=limits.free_weekly_limit,
        free_remaining=max(limits.free_weekly_limit - free_used, 0),
        pro_cost_cents_this_month=pro_cost,
        pro_budget_cents=limits.pro_budget_cents,
        pro_remaining_cents=max(limits.pro_budget_cents - pro_cost, 0),
        pro_monthly_price_cents=limits.pro_monthly_price_cents,
    )


def assert_can_extract(user: AuthUser, *, cache_hit: bool) -> None:
    q = get_quota(user)

    if not user.is_pro:
        if q.free_remaining <= 0:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FREE_WEEKLY_LIMIT",
                    "message": f"Free plan: {q.free_limit} recipe(s) per week. Upgrade to Pro.",
                    "free_used_this_week": q.free_used_this_week,
                    "free_limit": q.free_limit,
                },
            )
        return

    if cache_hit:
        return
    if q.pro_remaining_cents <= 0:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PRO_FAIR_USE_LIMIT",
                "message": "Pro fair-use limit reached this month (keeps margin).",
                "pro_cost_cents_this_month": q.pro_cost_cents_this_month,
                "pro_budget_cents": q.pro_budget_cents,
                "pro_monthly_price_cents": q.pro_monthly_price_cents,
            },
        )


def record_usage(
    *,
    user_id: UUID,
    kind: str,
    cost_cents: float,
    recipe_id: UUID | None,
    job_id: UUID | None,
) -> None:
    sb = get_supabase()
    sb.table("usage_events").insert(
        {
            "user_id": str(user_id),
            "kind": kind,
            "cost_cents": cost_cents,
            "recipe_id": str(recipe_id) if recipe_id else None,
            "job_id": str(job_id) if job_id else None,
        }
    ).execute()
