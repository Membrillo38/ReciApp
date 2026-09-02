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
    defaults = get_app_defaults()
    free_limit = profile.get("free_weekly_limit")
    if free_limit is None:
        free_limit = defaults.free_weekly_limit

    margin = profile.get("pro_margin_ratio")
    if margin is None:
        margin = defaults.pro_margin_ratio
    else:
        margin = float(margin)

    pro_price = profile.get("pro_monthly_price_cents")
    if pro_price is None:
        pro_price = defaults.default_pro_monthly_price_cents
    else:
        pro_price = int(pro_price)

    budget = float(pro_price) * (1.0 - margin)

    return UserLimits(
        free_weekly_limit=int(free_limit),
        pro_monthly_price_cents=int(pro_price),
        pro_margin_ratio=margin,
        pro_budget_cents=round(budget, 4),
    )


def price_cents_from_superwall(data: dict) -> int | None:
    price = data.get("price")
    if isinstance(price, (int, float)) and price > 0:
        return max(int(round(float(price) * 100)), 1)
    pip = data.get("priceInPurchasedCurrency")
    if isinstance(pip, (int, float)) and pip > 0:
        return max(int(round(float(pip) * 100)), 1)
    return None
