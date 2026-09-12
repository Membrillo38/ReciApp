from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from app.db import fetch_one

# Fair-use budgets are monthly. Convert billed period → monthly revenue.
_WEEKS_PER_MONTH = 52.0 / 12.0
# Mid of planned weekly A/B band ($6.99–$12.99), monthlyized: ~$9.99 × 52/12.
_DEFAULT_PRO_MONTHLY_CENTS = int(round(999 * _WEEKS_PER_MONTH))  # 4329


@dataclass
class UserLimits:
    free_weekly_limit: int
    pro_monthly_price_cents: int
    pro_margin_ratio: float
    pro_budget_cents: float


@dataclass
class AppDefaults:
    free_weekly_limit: int = 10
    pro_margin_ratio: float = 0.20
    default_pro_monthly_price_cents: int = _DEFAULT_PRO_MONTHLY_CENTS


@lru_cache(maxsize=1)
def _cached_defaults_key() -> str:
    return "defaults"


def get_app_defaults() -> AppDefaults:
    _cached_defaults_key()  # cache bust hook if needed later
    row = fetch_one("select * from app_settings where id = 1 limit 1")
    if not row:
        return AppDefaults()
    return AppDefaults(
        free_weekly_limit=int(row.get("free_weekly_limit") or 10),
        pro_margin_ratio=float(row.get("pro_margin_ratio") or 0.20),
        default_pro_monthly_price_cents=int(
            row.get("default_pro_monthly_price_cents") or _DEFAULT_PRO_MONTHLY_CENTS
        ),
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


def billing_period_from_superwall(data: dict) -> str:
    """Return week|month|year|unknown from payload fields or product id."""
    for key in ("period", "subscriptionPeriod", "billingPeriod", "productPeriod"):
        raw = data.get(key)
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if text in {"week", "weekly", "p1w"}:
            return "week"
        if text in {"month", "monthly", "p1m"}:
            return "month"
        if text in {"year", "yearly", "annual", "annually", "p1y"}:
            return "year"
    product = str(data.get("productId") or data.get("productIdentifier") or "").lower()
    if "_wk" in product or "weekly" in product:
        return "week"
    if "_mo" in product or "monthly" in product:
        return "month"
    if "_an" in product or "_yr" in product or "yearly" in product or "annual" in product:
        return "year"
    return "unknown"


def period_price_cents_from_superwall(data: dict) -> int | None:
    """Raw list/paid price for the billed period (cents)."""
    for key in (
        "price",
        "priceInPurchasedCurrency",
    ):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return max(int(round(float(value) * 100)), 1)
    return None


def monthly_price_cents_from_superwall(data: dict) -> int | None:
    """Convert billed period price to approximate monthly revenue (cents)."""
    period_cents = period_price_cents_from_superwall(data)
    if period_cents is None:
        return None
    period = billing_period_from_superwall(data)
    if period == "week":
        return max(int(round(period_cents * _WEEKS_PER_MONTH)), 1)
    if period == "year":
        return max(int(round(period_cents / 12.0)), 1)
    if period == "month":
        return period_cents
    # Unknown period: treat as monthly (legacy / one-shot). Better than inventing.
    return period_cents


def price_cents_from_superwall(data: dict) -> int | None:
    """Backward-compatible alias: period list price in cents."""
    return period_price_cents_from_superwall(data)


def proceeds_cents_from_superwall(data: dict) -> int | None:
    for key in ("proceeds", "netProceeds", "proceedsInPurchasedCurrency"):
        value = data.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return max(int(round(float(value) * 100)), 1)
    return None
