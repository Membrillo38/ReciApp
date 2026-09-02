"""Minimal import check. Run: python check.py"""
from app.main import app
from app.models import Platform
from app.platforms import detect_platform, youtube_video_id

assert app.title == "Recipe Extractor API"
assert detect_platform("https://www.tiktok.com/@x/video/1") == Platform.tiktok
assert detect_platform("https://youtu.be/abc123") == Platform.youtube
assert youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
print("ok")
