"""Behavioral regression coverage; all upstream traffic uses recording transports."""
import asyncio
import base64
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError
from svix.webhooks import Webhook

import app.auth as auth
import app.db as db
import app.main as main
import app.pipeline as pipeline
import app.security as security
import app.superwall as superwall
import app.worker as worker
import app.apple_notifications as apple
from app.config import Settings, settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    for name, value in {
        "supabase_url": "https://example.supabase.co",
        "supabase_expected_host": "example.supabase.co",
        "supabase_service_role_key": "sb_secret_fake_test_key",
        "maintenance_mode": False,
        "readiness_timeout_seconds": 0.1,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(main, "log_request", lambda **kwargs: None)


def fail(*args, **kwargs):
    raise AssertionError("unexpected database or paid work")


def test_public_sdk_rest_auth_urls_and_headers():
    seen = []
    uid = str(uuid4())
    def record(request):
        seen.append(request)
        if request.url.path == "/auth/v1/user":
            return httpx.Response(200, json={"id": uid, "aud": "authenticated", "app_metadata": {}, "user_metadata": {}, "created_at": "2026-09-08T00:00:00Z"})
        return httpx.Response(200, json=[])
    client, owner = db.create_service_client(transport=httpx.MockTransport(record))
    try:
        client.table("profiles").select("id").execute()
        client.table("profiles").update({"display_name": "Test"}).eq("id", uid).execute()
        assert client.auth.get_user("test-user-token").user.id == uid
    finally:
        owner.close()
    assert [r.url.path for r in seen] == ["/rest/v1/profiles", "/rest/v1/profiles", "/auth/v1/user"]
    assert all(r.url.host == "example.supabase.co" and r.url.scheme == "https" for r in seen)
    assert all(r.headers["apikey"] == settings.supabase_service_role_key for r in seen)
    assert seen[0].headers["authorization"] == "Bearer " + settings.supabase_service_role_key
    assert seen[0].headers["accept-profile"] == "public"
    assert seen[1].headers["content-profile"] == "public"
    assert seen[2].headers["authorization"] == "Bearer test-user-token"
    assert client.options.persist_session is False
    assert client.options.auto_refresh_token is False
    assert owner.is_closed


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadError, httpx.ReadTimeout, httpx.WriteError, httpx.WriteTimeout, httpx.RemoteProtocolError])
def test_safe_read_retries_exactly_once(error):
    calls = []
    def record(request):
        calls.append(request)
        raise error("upstream broke", request=request)
    with httpx.Client(transport=db.ReadRetryTransport(httpx.MockTransport(record))) as client:
        with pytest.raises(error):
            client.get("https://example.supabase.co/rest/v1/profiles")
    assert len(calls) == 2


@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
@pytest.mark.parametrize("after_headers", [False, True])
def test_ambiguous_mutation_never_replayed(method, after_headers):
    calls = []
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadError("response lost after commit")
            yield b""
    def record(request):
        calls.append(request)
        if after_headers:
            return httpx.Response(200, stream=BrokenStream())
        raise httpx.RemoteProtocolError("response lost after commit", request=request)
    with httpx.Client(transport=db.ReadRetryTransport(httpx.MockTransport(record))) as client:
        with pytest.raises((httpx.ReadError, httpx.RemoteProtocolError)):
            client.request(method, "https://example.supabase.co/rest/v1/profiles", json={"name": "test"})
    assert len(calls) == 1


def test_read_stream_failure_retries_and_closes_failed_response():
    closed = []
    calls = []
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            raise httpx.ReadTimeout("body failed")
            yield b""
        def close(self):
            closed.append(True)
    def record(request):
        calls.append(request)
        return httpx.Response(200, stream=BrokenStream()) if len(calls) == 1 else httpx.Response(200, json=[])
    with httpx.Client(transport=db.ReadRetryTransport(httpx.MockTransport(record))) as client:
        assert client.get("https://example.supabase.co/rest/v1/profiles").json() == []
    assert len(calls) == 2 and closed


@pytest.mark.parametrize("outcome", [401, 429, 500, 503, httpx.UnsupportedProtocol, httpx.LocalProtocolError, httpx.PoolTimeout])
def test_status_and_non_transient_errors_do_not_retry(outcome):
    calls = []
    def record(request):
        calls.append(request)
        if isinstance(outcome, int):
            return httpx.Response(outcome)
        raise outcome("local failure")
    with httpx.Client(transport=db.ReadRetryTransport(httpx.MockTransport(record))) as client:
        if isinstance(outcome, int):
            assert client.get("https://example.supabase.co").status_code == outcome
        else:
            with pytest.raises(outcome):
                client.get("https://example.supabase.co")
    assert len(calls) == 1


def config(**overrides):
    return Settings(_env_file=None, **{
        "supabase_url": "https://example.supabase.co",
        "supabase_expected_host": "example.supabase.co",
        "supabase_service_role_key": "sb_secret_test_key",
        **overrides,
    })


@pytest.mark.parametrize("url", ["", "http://example.supabase.co", "https://u:p@example.supabase.co", "https://example.supabase.co/rest/v1", "https://example.supabase.co?", "https://example.supabase.co#", "https://example.supabase.co/?key=secret", " https://example.supabase.co", "https://example.supabase.co\n", "https://example.supabase.co:8443", "https://other.supabase.co", "https://127.0.0.1", "https://example.supabase.co\\evil", "https://example.supabase.co:bad", "\x00https://example.supabase.co"])
def test_config_rejects_invalid_url_without_secrets(url):
    with pytest.raises(RuntimeError) as caught:
        config(supabase_url=url, supabase_service_role_key="SECRET_VALUE").validate_supabase()
    assert "SECRET_VALUE" not in str(caught.value)


def legacy_key(role="service_role", ref="example"):
    payload = base64.urlsafe_b64encode(json.dumps({"role": role, "ref": ref}).encode()).decode().rstrip("=")
    return "header." + payload + ".signature"


@pytest.mark.parametrize("key", ["", " ", "sb_publishable_test", "sb_secret_bad key", "jwt.invalid.signature", legacy_key(role="anon"), legacy_key(ref="other")])
def test_invalid_service_key_redacted(key):
    with pytest.raises(RuntimeError) as caught:
        config(supabase_service_role_key=key).validate_supabase()
    if len(key) > 1:
        assert key not in str(caught.value)


def test_modern_legacy_and_explicit_local_config():
    config().validate_supabase()
    config(supabase_service_role_key=legacy_key()).validate_supabase()
    config(supabase_url="http://127.0.0.1:54321", supabase_expected_host="127.0.0.1", environment="development", supabase_allow_local=True, supabase_service_role_key=legacy_key(ref="local")).validate_supabase()
    with pytest.raises(RuntimeError):
        config(supabase_url="http://127.0.0.1:54321", supabase_expected_host="127.0.0.1", supabase_allow_local=True).validate_supabase()


def test_invalid_config_fails_startup(monkeypatch):
    monkeypatch.setattr(settings, "supabase_expected_host", "wrong.supabase.co")
    with pytest.raises(RuntimeError, match="expected host"):
        with TestClient(main.app):
            pass


def test_startup_constructs_without_network_and_shutdown_closes(monkeypatch):
    db.reset_supabase()
    original_create = db.create_service_client
    owners = []
    def create():
        client, owner = original_create(transport=httpx.MockTransport(fail))
        owners.append(owner)
        return client, owner
    monkeypatch.setattr(db, "create_service_client", create)
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert len(owners) == 1 and not owners[0].is_closed
    assert owners[0].is_closed
    assert db._client is None


def test_health_never_reads_or_logs_db(monkeypatch):
    monkeypatch.setattr(main, "get_supabase", fail)
    monkeypatch.setattr(main, "log_request", fail)
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_readiness_bounded_redacted_and_cancels_probe(monkeypatch, outcome):
    finished = []
    async def probe():
        try:
            if outcome == "failure":
                raise httpx.ConnectError("SECRET_VALUE")
            if outcome == "timeout":
                await asyncio.sleep(30)
        finally:
            finished.append(True)
    monkeypatch.setattr(main, "probe_supabase", probe)
    monkeypatch.setattr(main, "log_request", fail)
    response = TestClient(main.app).get("/ready")
    assert response.status_code == (200 if outcome == "success" else 503)
    assert set(response.json()) == ({"status", "latency_ms", "maintenance"} if outcome == "success" else {"status", "latency_ms", "maintenance", "error"})
    assert "SECRET_VALUE" not in response.text
    assert response.json()["latency_ms"] < 1000
    assert finished == [True]


def test_readiness_wire_probe_uses_bounded_authenticated_read(monkeypatch):
    seen = []
    original = httpx.AsyncClient
    def record(request):
        seen.append(request)
        return httpx.Response(200, json=[])
    def client(**kwargs):
        assert kwargs["timeout"] == 0.1
        assert kwargs["follow_redirects"] is False
        return original(transport=httpx.MockTransport(record), **kwargs)
    monkeypatch.setattr(db.httpx, "AsyncClient", client)
    asyncio.run(db.probe_supabase())
    assert str(seen[0].url) == "https://example.supabase.co/rest/v1/profiles?select=id&limit=1"
    assert seen[0].headers["apikey"] == settings.supabase_service_role_key
    assert seen[0].headers["accept-profile"] == "public"


class FakeDB:
    def __init__(self, profile=None):
        self.rows = {"profiles": [copy.deepcopy(profile)] if profile else [], "subscription_events": [], "apple_notification_events": []}
        self.operations = []
        self.profile_race = None
        self.fail_profile_once = False
        self.fail_mark_once = False
    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self.operation, self.payload = [], "select", None
    def select(self, *args): return self
    def limit(self, *args): return self
    def eq(self, field, value): self.filters.append((field, value)); return self
    def is_(self, field, value): self.filters.append((field, None if value == "null" else value)); return self
    def insert(self, payload): self.operation, self.payload = "insert", payload; return self
    def update(self, payload): self.operation, self.payload = "update", payload; return self
    def upsert(self, payload): raise AssertionError("profile resurrection forbidden")
    def execute(self):
        self.db.operations.append((self.table, self.operation))
        if self.table == "profiles" and self.operation == "update":
            if self.db.profile_race:
                self.db.profile_race(self.db)
                self.db.profile_race = None
            if self.db.fail_profile_once:
                self.db.fail_profile_once = False
                raise httpx.ReadError("SECRET_VALUE")
        if self.table == "subscription_events" and self.operation == "update" and self.payload["status"] == "processed" and self.db.fail_mark_once:
            self.db.fail_mark_once = False
            raise httpx.ReadError("SECRET_VALUE")
        rows = self.db.rows[self.table]
        matched = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
        if self.operation == "insert":
            rows.append(copy.deepcopy(self.payload)); matched = [rows[-1]]
        if self.operation == "update":
            for row in matched: row.update(self.payload)
        return SimpleNamespace(data=copy.deepcopy(matched))


@pytest.mark.parametrize("profile", [None, {"deleted_at": "2026-09-08"}, {"display_name": "Test", "is_pro": True}])
def test_current_user_reads_only_and_denies_missing_deleted_profile(monkeypatch, profile):
    uid = uuid4()
    fake = FakeDB({"id": str(uid), **profile} if profile else None)
    fake.auth = SimpleNamespace(get_user=lambda token: SimpleNamespace(user=SimpleNamespace(id=str(uid), email="test@example.com")))
    monkeypatch.setattr(auth, "get_supabase", lambda: fake)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="user-token")
    if profile and not profile.get("deleted_at"):
        assert auth.current_user(creds).id == uid
    else:
        with pytest.raises(HTTPException) as caught: auth.current_user(creds)
        assert caught.value.status_code == 403
    assert all(operation == "select" for _, operation in fake.operations)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 429, 500, 503, None])
def test_auth_invalid_credentials_vs_outage(monkeypatch, status):
    def get_user(token):
        if status is None: raise httpx.ReadError("SECRET_VALUE")
        raise AuthApiError("SECRET_VALUE", status, None)
    monkeypatch.setattr(auth, "get_supabase", lambda: SimpleNamespace(auth=SimpleNamespace(get_user=get_user)))
    with pytest.raises(HTTPException) as caught:
        auth.current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="test-token"))
    assert caught.value.status_code == (401 if status in {400, 401, 403, 404, 422} else 503)
    assert "SECRET_VALUE" not in caught.value.detail


def test_missing_auth_user_and_bearer_denied(monkeypatch):
    monkeypatch.setattr(auth, "get_supabase", lambda: SimpleNamespace(auth=SimpleNamespace(get_user=lambda _: SimpleNamespace(user=None))))
    for creds in [None, HTTPAuthorizationCredentials(scheme="Bearer", credentials="gone")]:
        with pytest.raises(HTTPException) as caught: auth.current_user(creds)
        assert caught.value.status_code == 401


@pytest.mark.parametrize("method,path", [("POST", "/v1/extract"), ("POST", "/v1/webhooks/superwall"), ("POST", "/v1/webhooks/apple"), ("PATCH", "/v1/me"), ("DELETE", "/v1/me"), ("POST", "/dashboard/login")])
def test_maintenance_blocks_writes_before_auth_and_preserves_correlation(monkeypatch, method, path):
    monkeypatch.setattr(settings, "maintenance_mode", True)
    monkeypatch.setattr(main, "get_supabase", fail)
    monkeypatch.setattr(main, "log_request", fail)
    response = TestClient(main.app).request(method, path, headers={"X-Request-ID": "maintenance-test"}, json={})
    assert response.status_code == 503 and response.headers["retry-after"] == "30"
    assert response.headers["x-correlation-id"] == "maintenance-test"


def test_maintenance_read_side_effects_workers_and_queued_jobs(monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", True)
    for module in [main, worker, security, apple, superwall]:
        monkeypatch.setattr(module, "get_supabase", fail)
    for name in ["fetch_media_info", "update_job", "get_recipe", "build_recipe", "translate_recipe"]:
        monkeypatch.setattr(pipeline, name, fail)
    uid, jid, rid = uuid4(), uuid4(), uuid4()
    released = []
    monkeypatch.setattr(pipeline, "release_job", lambda user_id: released.append(user_id))
    assert worker._claim_next_job() is None
    worker._run_claimed_job({})
    pipeline.run_extract_job(jid, uid, "https://example.com", "source", "en-US")
    pipeline.run_translation_job(jid, uid, rid, "es-ES")
    assert released == [uid, uid]
    security.audit_security_event(event="test")
    with pytest.raises(HTTPException) as caught:
        main.get_job_status(jid, object(), "en-US", auth.AuthUser(uid, None, None, False, None))
    assert caught.value.status_code == 503
    with pytest.raises(HTTPException):
        main._ensure_translation_job(user=None, recipe_id=rid, source_url_raw="", source_url_norm="", language_code="es-ES", background=None)
    with pytest.raises(HTTPException): superwall.apply_superwall_event({})
    with pytest.raises(HTTPException): apple.process_signed_notification("invalid")
    assert main._expire_stale_job({"status": "pending", "updated_at": "2000-01-01T00:00:00+00:00"}) is False


def event(uid, name="initial_purchase", seconds=0, event_id="event-1"):
    return {"id": event_id, "type": name, "createdAt": (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(), "data": {"appUserId": str(uid), "price": 9.99}}


def use_superwall(monkeypatch, fake):
    monkeypatch.setattr(superwall, "get_supabase", lambda: fake)
    monkeypatch.setattr(superwall, "get_app_defaults", lambda: SimpleNamespace(default_pro_monthly_price_cents=999, free_weekly_limit=1))


@pytest.mark.parametrize("state", ["existing", "missing", "deleted", "deleted_during_update", "removed_during_update"])
def test_superwall_does_not_recreate_profiles(monkeypatch, state):
    uid = uuid4()
    profile = {"id": str(uid), "is_pro": False}
    if state == "deleted": profile["deleted_at"] = "2026-09-08"
    fake = FakeDB(None if state == "missing" else profile)
    if state == "deleted_during_update": fake.profile_race = lambda db: db.rows["profiles"][0].update(deleted_at="2026-09-08")
    if state == "removed_during_update": fake.profile_race = lambda db: db.rows.update(profiles=[])
    use_superwall(monkeypatch, fake)
    result = superwall.apply_superwall_event(event(uid))
    assert result["updated"] is (state == "existing")
    if state != "existing": assert result["skipped"] == "profile_unavailable"
    assert ("profiles", "insert") not in fake.operations


def test_superwall_replay_and_out_of_order(monkeypatch):
    uid = uuid4(); fake = FakeDB({"id": str(uid)})
    use_superwall(monkeypatch, fake)
    payload = event(uid)
    assert superwall.apply_superwall_event(payload)["updated"]
    assert superwall.apply_superwall_event(payload)["skipped"] == "duplicate"
    assert superwall.apply_superwall_event(event(uid, name="expiration", seconds=-20, event_id="older"))["skipped"] == "out_of_order"
    assert fake.rows["profiles"][0]["is_pro"] is True
    assert fake.operations.count(("profiles", "update")) == 1


@pytest.mark.parametrize("failure", ["fail_profile_once", "fail_mark_once"])
def test_failed_webhook_retry_is_not_silently_successful(monkeypatch, failure):
    uid = uuid4(); fake = FakeDB({"id": str(uid)})
    setattr(fake, failure, True); use_superwall(monkeypatch, fake)
    payload = event(uid)
    with pytest.raises(HTTPException) as caught: superwall.apply_superwall_event(payload)
    assert caught.value.status_code == 503
    assert fake.rows["subscription_events"][0]["status"] == "failed"
    assert "SECRET_VALUE" not in json.dumps(fake.rows)
    result = superwall.apply_superwall_event(payload)
    assert result["updated"] or result["skipped"] == "duplicate"
    assert fake.rows["profiles"][0]["is_pro"] is True
    assert fake.rows["subscription_events"][0]["status"] == "processed"


def test_superwall_concurrent_newer_event_wins(monkeypatch):
    uid = uuid4(); fake = FakeDB({"id": str(uid)})
    use_superwall(monkeypatch, fake)
    fake.profile_race = lambda db: db.rows["profiles"][0].update(subscription_event_at=(datetime.now(timezone.utc)+timedelta(seconds=5)).isoformat(), subscription_event_id="newer", is_pro=False)
    assert superwall.apply_superwall_event(event(uid))["skipped"] == "out_of_order"
    assert fake.rows["profiles"][0]["is_pro"] is False


def test_signed_superwall_route_and_replay(monkeypatch):
    uid = uuid4(); fake = FakeDB({"id": str(uid)})
    use_superwall(monkeypatch, fake)
    secret = "whsec_" + base64.b64encode(b"test-signature-key").decode()
    monkeypatch.setattr(settings, "superwall_webhook_secret", secret)
    raw = json.dumps(event(uid))
    timestamp = datetime.now(timezone.utc)
    headers = {"svix-id": "delivery-1", "svix-timestamp": str(int(timestamp.timestamp())), "svix-signature": Webhook(secret).sign("delivery-1", timestamp, raw), "Content-Type": "application/json"}
    client = TestClient(main.app)
    assert client.post("/v1/webhooks/superwall", content=raw).status_code == 400
    response = client.post("/v1/webhooks/superwall", content=raw, headers=headers)
    assert response.status_code == 200 and response.json()["updated"] is True
    assert client.post("/v1/webhooks/superwall", content=raw, headers=headers).json()["skipped"] == "duplicate"
    assert client.post("/v1/webhooks/superwall", content=raw+" ", headers=headers).status_code == 400


@pytest.mark.parametrize("state", ["existing", "missing", "deleted"])
def test_apple_never_recreates_profile(monkeypatch, state):
    uid = uuid4(); profile = {"id": str(uid)}
    if state == "deleted": profile["deleted_at"] = "2026-09-08"
    fake = FakeDB(None if state == "missing" else profile)
    monkeypatch.setattr(apple, "get_supabase", lambda: fake)
    monkeypatch.setattr(apple, "verify_jws", lambda value: {"notificationUUID": "apple-event", "notificationType": "SUBSCRIBED", "data": {"signedTransactionInfo": "transaction"}} if value == "notification" else {"appAccountToken": str(uid)})
    result = apple.process_signed_notification("notification")
    assert result["updated"] is (state == "existing")
    assert ("profiles", "insert") not in fake.operations


@pytest.mark.parametrize("status", [503, 520])
def test_real_sdk_status_errors_do_not_trigger_hidden_retries(status):
    calls = []
    def record(request):
        calls.append(request)
        return httpx.Response(status, json={"message": "upstream unavailable"})
    client, owner = db.create_service_client(transport=httpx.MockTransport(record))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            client.table("profiles").select("id").execute()
    finally:
        owner.close()
    assert len(calls) == 1


def test_profile_database_outage_returns_503(monkeypatch):
    fake = SimpleNamespace(auth=SimpleNamespace(get_user=lambda _: SimpleNamespace(user=SimpleNamespace(id=str(uuid4())))), table=lambda _: fail())
    monkeypatch.setattr(auth, "get_supabase", lambda: fake)
    with pytest.raises(HTTPException) as caught:
        auth.current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials="token"))
    assert caught.value.status_code == 503


def test_maintenance_probes_remain_available(monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", True)
    async def probe(): pass
    monkeypatch.setattr(main, "probe_supabase", probe)
    monkeypatch.setattr(main, "log_request", fail)
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    response = client.get("/ready")
    assert response.status_code == 200 and response.json()["maintenance"] is True


def test_admin_creation_updates_trigger_profile_only(monkeypatch):
    uid = uuid4(); fake = FakeDB()
    fake.auth = SimpleNamespace(admin=SimpleNamespace(create_user=lambda _: SimpleNamespace(user=SimpleNamespace(id=uid))))
    monkeypatch.setattr(main, "get_supabase", lambda: fake)
    body = main.AdminUserCreate(email="test@example.com", display_name="Test", is_pro=False)
    with pytest.raises(HTTPException) as caught:
        main.admin_create_user(None, body)
    assert caught.value.status_code == 503
    assert fake.operations == [("profiles", "update")]


def test_sdk_initialization_failure_is_redacted_and_closes_owner(monkeypatch):
    owners = []
    original = httpx.Client
    def owner(**kwargs):
        result = original(**kwargs); owners.append(result); return result
    monkeypatch.setattr(db.httpx, "Client", owner)
    def broken(*args, **kwargs): raise ValueError("SECRET_VALUE")
    monkeypatch.setattr(db, "create_client", broken)
    with pytest.raises(RuntimeError) as caught: db.create_service_client(transport=httpx.MockTransport(fail))
    assert str(caught.value) == "Supabase client initialization failed"
    assert owners[0].is_closed


def test_maintenance_job_get_rejects_before_side_effects(monkeypatch):
    monkeypatch.setattr(settings, "maintenance_mode", True)
    monkeypatch.setattr(main, "get_job", fail)
    main.app.dependency_overrides[auth.current_user] = lambda: auth.AuthUser(uuid4(), None, None, False, None)
    try:
        response = TestClient(main.app).get("/v1/jobs/" + str(uuid4()), headers={"X-Request-ID": "job-read"})
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.headers["x-correlation-id"] == "job-read"


@pytest.mark.parametrize("status,expected", [("received", True), ("failed", True), ("processed", False), ("skipped", False)])
def test_concurrent_receipt_conflict_requires_terminal_success(monkeypatch, status, expected):
    from postgrest.exceptions import APIError
    fake = FakeDB()
    original = Query.execute
    def execute(query):
        if query.table == "subscription_events" and query.operation == "insert":
            query.db.rows[query.table].append({"event_id": "conflict", "status": status})
            raise APIError({"code": "23505", "message": "duplicate key", "details": None, "hint": None})
        return original(query)
    monkeypatch.setattr(Query, "execute", execute)
    use_superwall(monkeypatch, fake)
    assert superwall._record_event("conflict", "renewal", datetime.now(timezone.utc), None, {}) is expected


@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_real_sdk_transport_failure_bound(method):
    calls = []
    def record(request):
        calls.append(request)
        raise httpx.ReadError("upstream disconnected", request=request)
    client, owner = db.create_service_client(transport=httpx.MockTransport(record))
    try:
        with pytest.raises(httpx.ReadError):
            query = client.table("profiles")
            (query.select("id") if method == "GET" else query.update({"display_name": "Test"})).execute()
    finally:
        owner.close()
    assert len(calls) == (2 if method == "GET" else 1)
