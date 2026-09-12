from app.limits import (
    billing_period_from_superwall,
    monthly_price_cents_from_superwall,
    period_price_cents_from_superwall,
)


def test_weekly_product_monthlyizes_for_fair_use():
    data = {"price": 9.99, "productId": "reciapp_wk_999"}
    assert billing_period_from_superwall(data) == "week"
    assert period_price_cents_from_superwall(data) == 999
    # 999 × 52/12 ≈ 4329
    assert monthly_price_cents_from_superwall(data) == 4329


def test_yearly_product_divides_by_twelve():
    data = {"price": 49.99, "productId": "reciapp_an_4999_3trial"}
    assert billing_period_from_superwall(data) == "year"
    assert period_price_cents_from_superwall(data) == 4999
    assert monthly_price_cents_from_superwall(data) == 417


def test_explicit_period_field_beats_product_id():
    data = {"price": 9.99, "productId": "weird_sku", "period": "week"}
    assert billing_period_from_superwall(data) == "week"
    assert monthly_price_cents_from_superwall(data) == 4329


def test_missing_price_returns_none():
    assert period_price_cents_from_superwall({"productId": "reciapp_wk"}) is None
    assert monthly_price_cents_from_superwall({"productId": "reciapp_wk"}) is None
