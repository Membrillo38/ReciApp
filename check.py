"""Smoke checks. Run: python check.py"""
from app.main import app
from app.models import Platform
from app.platforms import detect_platform, youtube_video_id
from app.url_norm import normalize_url
from app.config import pro_monthly_budget_cents
from app.costing import estimate_miss_cost_cents

assert app.title == "ReciApp API"
assert detect_platform("https://www.tiktok.com/@x/video/1") == Platform.tiktok
assert detect_platform("https://youtu.be/abc123") == Platform.youtube
assert youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
assert normalize_url("https://youtu.be/dQw4w9WgXcQ?si=abc") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
assert normalize_url("https://www.tiktok.com/@u/video/123?utm_source=x") == "https://www.tiktok.com/@u/video/123"
assert pro_monthly_budget_cents() == 499 * 0.8
assert estimate_miss_cost_cents(used_transcribe=True, duration_seconds=60) > 0
print("ok")
