"""Smoke checks. Run: python check.py"""
from app.main import app
from app.models import Platform
from app.platforms import detect_platform
from app.url_norm import normalize_url
import app.limits as limits
from app.costing import estimate_miss_cost_cents

assert app.title == "ReciApp API"
assert detect_platform("https://www.tiktok.com/@x/video/1") == Platform.tiktok
assert normalize_url("https://youtu.be/dQw4w9WgXcQ?si=abc") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

limits.get_app_defaults = lambda: limits.AppDefaults()
resolved_limits = limits.resolve_user_limits(
    {"is_pro": True, "pro_monthly_price_cents": 999, "pro_margin_ratio": 0.20, "free_weekly_limit": 1}
)
assert resolved_limits.pro_budget_cents == round(999 * 0.8, 4)
assert resolved_limits.free_weekly_limit == 1
assert estimate_miss_cost_cents(used_transcribe=True, duration_seconds=60) > 0
print("ok")
