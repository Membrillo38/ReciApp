from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app import spend


def test_numeric_casts_float_to_decimal():
    assert spend._numeric(100.0) == Decimal("100.0")
    assert spend._numeric(Decimal("1.5")) == Decimal("1.5")


def test_reserve_spend_passes_decimal_not_float(monkeypatch):
    captured = {}

    def fake_fetch(sql, params):
        captured["params"] = params
        return {
            "allowed": True,
            "reason": None,
            "reservation_id": str(uuid4()),
            "reserved_cents": Decimal("100"),
        }

    monkeypatch.setattr(spend.settings, "billing_guard_enabled", True)
    monkeypatch.setattr(spend, "fetch_one", fake_fetch)
    result = spend.reserve_spend(user_id=uuid4(), job_id=uuid4())
    assert result.reserved_cents == 100.0
    for value in captured["params"][2:]:
        assert isinstance(value, Decimal)


def test_reserve_spend_disabled_fails_closed(monkeypatch):
    monkeypatch.setattr(spend.settings, "billing_guard_enabled", False)
    with pytest.raises(HTTPException) as exc:
        spend.reserve_spend(user_id=uuid4(), job_id=uuid4())
    assert exc.value.status_code == 503
    assert exc.value.detail == "Usage protection is disabled"
