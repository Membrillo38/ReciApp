from pathlib import Path


def test_superwall_is_configured_and_identified_with_supabase_user():
    service = Path("IosAPP/ReciApp/Services/SubscriptionService.swift").read_text(encoding="utf-8")
    auth = Path("IosAPP/ReciApp/Services/AuthService.swift").read_text(encoding="utf-8")
    assert "Superwall.configure(apiKey: AppConfig.superwallPublicKey)" in service
    assert "Superwall.shared.identify(userId: value)" in service
    assert 'setUserAttributes(["supabase_user_id": value])' in service
    assert "func restorePurchases" in service
    assert "SubscriptionService.shared.identify" in auth


def test_superwall_webhook_rejects_unsigned_payloads_in_production_path():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert 'if not settings.superwall_webhook_secret:' in source
    assert 'raise HTTPException(status_code=503, detail="Webhook verification unavailable")' in source
    assert 'raise HTTPException(status_code=400, detail="Invalid application id")' in source
    assert "apply_superwall_event(payload, event_id=svix_id)" in source
