# Task 1 — Backend connection, auth and maintenance

Status: DONE_WITH_CONCERNS (local implementation complete; production activation intentionally not performed).

## Scope and recovery

Work completed in `/Users/andrescasillas/Desktop/ReciApp/.worktrees/connection-reset-plan`. Inspected `.recovery/01a08163-8dbd-7763-a2c9-45fe2d8fb21d.json` and replayed only the three local implementation patches after reviewing their contents. Installation used a task-local `.venv`; the original repository virtualenv was read-only. No deployment, push, merge, remote data mutation, paid API call, upload or iOS edit occurred. The controller approved narrow additional changes to `app/apple_notifications.py`, `app/security.py` and `render.worker.yaml`.

## Changes

- Replaced private Supabase imports/subclasses with public `create_client` and `ClientOptions`; pinned `supabase==2.31.0` and compatible `pydantic==2.11.7`.
- Added an owned HTTP/1.1 transport with bounded connection pools and timeouts. Genuine transient failures retry safe reads exactly once, including response-body failures; mutations never replay. Responses are closed, and the shared client closes after lifespan/worker shutdown. Individual failed requests no longer reset a pool used by other requests.
- PostgREST 2.31.0 has its own default HTTP 503/520 retry loop. A public HTTPX response hook raises these status failures before that loop. This prevents hidden status retries; a redacted retriable 503 reaches the API client. Actual SDK tests verify the request counts.
- Startup validates the Supabase root URL, expected hostname, HTTPS, port, whitespace/control characters and service-key configuration without contacting Supabase. Modern secret keys and legacy service-role JWTs with a matching project reference are accepted. Explicit local HTTP development requires both development environment and local opt-in. Errors never include key contents. JWT parsing here checks configuration consistency, not cryptographic authentication.
- `/health` performs no database calls or database request logging. `/ready` uses one async authenticated REST read with a 3-second default overall deadline, cancellation and owned-client cleanup. Responses expose status, latency, maintenance and error class only; failure is 503.
- `current_user` retains server-side `get_user`, makes profile reads only and denies absent/deleted profiles without recreating them. Invalid credentials return 401; Auth and profile-storage outages return retriable 503.
- Superwall never inserts/upserts profiles. Conditional updates check deletion and prior event state, so deletion races cannot resurrect users and older concurrent events cannot overwrite newer events. Received/failed event receipts remain retryable. Failed processing/status writes do not become successful replays. Signature verification and event ordering/idempotency remain intact.
- Removed profile creation fallback from admin creation and Apple notifications. Admin creation updates only the profile created by the auth trigger; missing profile returns 503. Apple updates only an existing non-deleted profile and reports skipped when none was changed.
- Maintenance blocks HTTP mutations/imports/webhooks before auth, retaining correlation and Retry-After headers. Side-effecting job GETs/translation enqueue are blocked; stale-job updates, audit inserts and request metrics are suppressed. Worker claim/dispatch and queued extraction/translation entry points check maintenance before new database or paid work.
- Main Blueprint now proposes free web plan, `/health`, `autoDeployTrigger: "off"`, expected host, 10-second upstream timeout, 3-second readiness timeout and maintenance false. Optional worker Blueprint preserves its existing starter plan, adds matching configuration and disables automatic deployment. No service was created or changed.
- iOS static tests explicitly skip when ignored iOS sources are absent. The obsolete private-client test now verifies full SDK URLs/headers. The original user's extra auth regression test was restored verbatim from evidence. A narrow `pytest.ini` filter suppresses only the existing third-party Starlette/AnyIO alias deprecation.

## Evidence and verification

All commands ran from the persistent worktree unless stated otherwise.

1. Original regression: saved `git show HEAD:app/db.py` to `.recovery/original-db.py`, loaded it using the original read-only `.venv/bin/python` with Supabase 2.11.0, and replaced its transport with `httpx.MockTransport`. Recorded result: `{"url": "/profiles?select=id", "headers": {}}`, followed by `ValueError`. Evidence: `.recovery/original-sdk-regression.json`.
2. Environment: `/Users/andrescasillas/Desktop/ReciApp/.venv/bin/python -m venv .venv`; `.venv/bin/python -m pip install -r requirements.txt pytest==8.3.4`. Network-restricted install failed initially; approved package installation then succeeded in the isolated virtualenv. `.recovery/pip.log` records installation.
3. Focused final behavioral tests: `.venv/bin/python -m pytest -q tests/test_connection_reset.py` — **100 passed in 0.74s**. Evidence: `.recovery/focused-tests.log`.
4. Full suite before restoration of the extra user test: `.venv/bin/python -m pytest -q` — **165 passed in 0.65s**, no warnings. Evidence: `.recovery/full-tests.log`.
5. Restored original user's test: `.venv/bin/python -m pytest -q tests/test_reliability_contract.py::test_ios_auth_emits_local_session_without_accepting_an_expired_initial_session` — **1 passed in 0.39s**. This was the only subsequent test/code-content change; 166 tests are now present, with the final full run plus this isolated restoration check covering them.
6. Backend-only proof: copied tracked working files plus the new test and pytest configuration into `.recovery/backend-only`, deliberately excluding ignored iOS sources, then ran the task virtualenv's Python with `-m pytest -q -rs` from that directory — **157 passed, 8 explicit iOS skips in 0.70s**. This preceded restoration of the extra iOS-only test, which uses the same skip condition. Evidence: `.recovery/backend-only-tests.log`.
7. `.venv/bin/python -m pip --disable-pip-version-check --no-cache-dir check` — **No broken requirements found.**
8. `.venv/bin/python -m compileall -q app` and `git diff --check` — success.
9. Original user-test evidence remains unchanged: `.evidence/original-test_reliability_contract.py`, SHA-256 `5f516e2e7d7b64b09e7715b286d4001be3ab71d3f9fa2d69b04e232e55124228`. All original test functions are preserved except the explicitly obsolete private-client test, replaced with SDK wire-contract coverage.

Coverage includes real SDK REST/Auth URL/header capture, service/user authorization separation, schema headers, read retry bounds, response-body failure, no ambiguous mutation replay, hidden SDK status retries, invalid configuration/startup, no-network startup and shutdown ownership, liveness, readiness cancellation/failure, missing/deleted Auth/profile records, Auth service failures, maintenance write/GET/background/worker guards, signed Superwall requests and tamper rejection, absent/deleted/racing profiles, duplicate/older deliveries, insert-conflict receipt states, failed processing retry and status-write failure recovery, and Apple/admin profile non-recreation.

Official Supabase changelog was fetched and reviewed locally (`.recovery/supabase-changelog.md`); current public client APIs and Render Blueprint `autoDeployTrigger` support were also verified by the controller in the preceding turn. References: https://supabase.com/docs/reference/python/initializing and https://render.com/docs/blueprint-spec.

## Self-review and activation concerns

- No private Supabase imports/subclasses or profile upserts remain in the application. Default service REST and Auth paths use the owned transport; tests execute the real pinned SDK.
- Configure `SUPABASE_EXPECTED_HOST` and the intended service key on every writer before future activation. A mismatched or omitted host now intentionally prevents startup. Modern secret keys cannot reveal a project reference locally; readiness establishes upstream acceptance after activation.
- Enable maintenance on every web/worker process and any other writer, then drain all in-flight jobs before backup/reset. Environment flags are process settings; changing one service does not stop other services. Maintenance does not cancel already-running paid/external requests.
- Deferred request-local background jobs stay pending, with their existing durable state/reservations. Resume them through the durable worker after maintenance; ordinary import retries may attach to existing pending jobs rather than dispatch them again. If the optional worker remains disabled, an operator must explicitly reconcile pending jobs/reservations before reopening imports.
- Liveness success proves only that the process is alive. Readiness uses mocked transports in these local tests; no production availability claim is made here.
- `render.yaml` is a local proposal. The actual Render plan/configuration remains unchanged. Optional worker starter tier remains a separate paid proposal and was not activated.
