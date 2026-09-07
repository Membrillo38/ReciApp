from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.db import get_supabase


@dataclass
class UserLimits:
    free_weekly_limit: int
    pro_monthly_price_cents: int
    pro_margin_ratio: float
    pro_budget_cents: float


@dataclass
class AppDefaults:
    free_weekly_limit: int = 1
    pro_margin_ratio: float = 0.20
    default_pro_monthly_price_cents: int = 499


@lru_cache(maxsize=1)
def _cached_defaults_key() -> str:
    return "defaults"


def get_app_defaults() -> AppDefaults:
    _cached_defaults_key()  # cache bust hook if needed later
    sb = get_supabase()
    res = sb.table("app_settings").select("*").eq("id", 1).limit(1).execute()
    row = (res.data or [None])[0]
    if not row:
        return AppDefaults()
    return AppDefaults(
        free_weekly_limit=int(row.get("free_weekly_limit") or 1),
        pro_margin_ratio=float(row.get("pro_margin_ratio") or 0.20),
        default_pro_monthly_price_cents=int(row.get("default_pro_monthly_price_cents") or 499),
    )


def resolve_user_limits(profile: dict) -> UserLimits:
    free_limit = profile.get("free_weekly_limit")
    margin = profile.get("pro_margin_ratio")
    pro_price = profile.get("pro_monthly_price_cents")

    # Do not make quota checks depend on a second remote read when the profile
    # already contains all values needed to resolve its limits.
    if free_limit is None or margin is None or pro_price is None:
        defaults = get_app_defaults()
        if free_limit is None:
            free_limit = defaults.free_weekly_limit
        if margin is None:
            margin = defaults.pro_margin_ratio
        if pro_price is None:
            pro_price = defaults.default_pro_monthly_price_cents

    margin = float(margin)
    pro_price = int(pro_price)

    budget = float(pro_price) * (1.0 - margin)

    return UserLimits(
        free_weekly_limit=int(free_limit),
        pro_monthly_price_cents=int(pro_price),
        pro_margin_ratio=margin,
        pro_budget_cents=round(budget, 4),
    )


def price_cents_from_superwall(data: dict) -> int | None:
    for key in (
        "price",
        "priceInPurchasedCurrency",
    ):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return max(int(round(float(value) * 100)), 1)
    return None


def proceeds_cents_from_superwall(data: dict) -> int | None:
    for key in ("proceeds", "netProceeds", "proceedsInPurchasedCurrency"):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return max(int(round(float(value) * 100)), 1)
    return None
