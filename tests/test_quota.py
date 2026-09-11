from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.auth import AuthUser
from app import quota


def _limits_row():
    return {
        "free_weekly_limit": 1,
        "pro_monthly_price_cents": 499,
        "pro_margin_ratio": 0.20,
        "is_pro": False,
    }


def _patch_quota_reads(monkeypatch, *, miss_count: int):
    def fake_fetch_one(sql, params=None):
        text = " ".join(sql.split())
        if "from profiles" in text:
            return _limits_row()
        if "count(*) as count" in text:
            assert params[1] == datetime(datetime.now(timezone.utc).year, 1, 1, tzinfo=timezone.utc)
            assert "kind = 'extract_miss'" in text
            return {"count": miss_count}
        if "sum(cost_cents)" in text:
            return {"cost": 0}
        raise AssertionError(text)

    monkeypatch.setattr(quota, "fetch_one", fake_fetch_one)


def test_free_user_blocked_after_10_recipes_this_year(monkeypatch):
    user = AuthUser(uuid4(), None, None, False, None)
    _patch_quota_reads(monkeypatch, miss_count=10)

    status = quota.get_quota(user)
    assert status.free_limit == 10
    assert status.free_used_this_week == 10
    assert status.free_remaining == 0

    with pytest.raises(HTTPException) as exc:
        quota.assert_can_extract(user, cache_hit=False)
    assert exc.value.status_code == 403
    assert exc.value.detail["code"] == "FREE_WEEKLY_LIMIT"
    assert "per year" in exc.value.detail["message"]


def test_free_user_allowed_under_yearly_cap(monkeypatch):
    user = AuthUser(uuid4(), None, None, False, None)
    _patch_quota_reads(monkeypatch, miss_count=9)

    status = quota.get_quota(user)
    assert status.free_remaining == 1
    quota.assert_can_extract(user, cache_hit=False)


def test_pro_user_skips_yearly_recipe_cap(monkeypatch):
    user = AuthUser(uuid4(), None, None, True, None)
    _patch_quota_reads(monkeypatch, miss_count=100)
    quota.assert_can_extract(user, cache_hit=False)
