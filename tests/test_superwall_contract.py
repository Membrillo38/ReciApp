import pytest
from pathlib import Path


@pytest.mark.skipif(not Path("IosAPP/ReciApp").is_dir(), reason="Ignored iOS sources unavailable in backend-only checkout")
def test_superwall_is_configured_and_identified_with_app_user():
    service = Path("IosAPP/ReciApp/Services/SubscriptionService.swift").read_text(encoding="utf-8")
    auth = Path("IosAPP/ReciApp/Services/AuthService.swift").read_text(encoding="utf-8")
    assert "Superwall.configure(apiKey: AppConfig.superwallPublicKey)" in service
    assert "Superwall.shared.identify(userId: value)" in service
    # Prefer `user_id`; older builds may still send legacy `supabase_user_id`.
    assert (
        'setUserAttributes(["user_id": value])' in service
        or 'setUserAttributes(["supabase_user_id": value])' in service
    )
    assert "func restorePurchases" in service
    assert "SubscriptionService.shared.identify" in auth


def test_superwall_webhook_rejects_unsigned_payloads_in_production_path():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert 'if not settings.superwall_webhook_secret:' in source
    assert 'raise HTTPException(status_code=503, detail="Webhook verification unavailable")' in source
    assert 'raise HTTPException(status_code=400, detail="Invalid application id")' in source
    assert "apply_superwall_event(payload, event_id=svix_id)" in source


def test_server_extracts_app_user_id_not_hosted_auth():
    source = Path("app/superwall.py").read_text(encoding="utf-8")
    assert "def extract_app_user_id" in source
    assert "no_user_id" in source
    assert "no_supabase_user_id" not in source
