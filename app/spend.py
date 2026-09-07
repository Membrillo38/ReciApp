from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from app.config import settings
from app.db import get_supabase


@dataclass(frozen=True)
class SpendReservation:
    reservation_id: UUID
    reserved_cents: float


def reserve_spend(*, user_id: UUID, job_id: UUID) -> SpendReservation:
    """Atomically reserve worst-case spend in Postgres; fail closed if unavailable."""
    if not settings.billing_guard_enabled:
        raise HTTPException(status_code=503, detail="Usage protection is disabled")
    try:
        result = get_supabase().rpc(
            "reserve_api_spend",
            {
                "p_user_id": str(user_id),
                "p_job_id": str(job_id),
                "p_reserved_cents": float(settings.max_job_cost_cents),
                "p_daily_budget_cents": float(settings.daily_api_budget_cents),
                "p_monthly_budget_cents": float(settings.monthly_api_budget_cents),
                "p_user_monthly_budget_cents": float(settings.user_monthly_budget_cents),
            },
        ).execute()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Usage protection unavailable") from exc

    row = (result.data or [None])[0]
    if not isinstance(row, dict) or not row.get("allowed"):
        reason = str((row or {}).get("reason") or "budget_exhausted")
        raise HTTPException(
            status_code=403,
            detail={"code": "SPEND_LIMIT", "message": "Usage budget reached.", "reason": reason},
        )
    reservation_id = row.get("reservation_id")
    if not reservation_id:
        raise HTTPException(status_code=503, detail="Usage protection unavailable")
    return SpendReservation(UUID(str(reservation_id)), float(row.get("reserved_cents") or settings.max_job_cost_cents))


def settle_spend(*, job_id: UUID, actual_cents: float, status: str) -> None:
    try:
        get_supabase().rpc(
            "settle_api_spend",
            {
                "p_job_id": str(job_id),
                "p_actual_cents": max(float(actual_cents), 0.0),
                "p_status": status,
            },
        ).execute()
    except Exception:
        # The reservation remains in place, which is safer than releasing money
        # after a failed settlement call.
        pass


def conservative_failure_cost(*, openai_called: bool, estimated_cents: float) -> float:
    if not openai_called:
        return 0.0
    return max(float(estimated_cents), float(settings.cost_text_cents_per_extract))
