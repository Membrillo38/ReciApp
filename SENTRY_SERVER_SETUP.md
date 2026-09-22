# Sentry server setup

## Runtime

Backend: Python 3.12, FastAPI 0.115, Uvicorn, PostgreSQL via `psycopg`, `httpx`, PyJWT. Official `sentry-sdk[fastapi]` initializes in `app/observability.py` from `app/main.py`.

Empty `SENTRY_DSN` disables Sentry. No DSN or credential belongs in Git.

## Environment variables

Configure in hosting secrets/environment settings:

```text
SENTRY_DSN=https://<key>@<org>.ingest.sentry.io/<project>
SENTRY_ENVIRONMENT=production
SENTRY_RELEASE=reciapp-server@<git-sha-or-version>
SENTRY_TRACES_SAMPLE_RATE=0
```

Keep traces at `0` unless needed. Existing auth variables remain required: `AUTH_JWT_SECRET`, `DATABASE_URL`, Apple bundle/team/key/private key variables. Add same values to every web/worker process that emits auth events; restart after change. No deploy performed.

## Contract and logs

App sends `X-Request-ID`. Server preserves valid value as `request_id`, creates `correlation_id`, returns `X-Correlation-ID`. Auth failures:

```json
{"code":"APPLE_TOKEN_INVALID","message":"Apple identity token rejected","request_id":"...","correlation_id":"..."}
```

Logs include `endpoint`, `method`, `status`, `server_code`, `request_id`, `correlation_id`, `duration_ms`. Tokens, request bodies, cookies, authorization headers, identity tokens, authorization codes, access tokens, refresh tokens, passwords excluded.

Sentry tags: `auth_flow`, `auth_phase`, `auth_endpoint`, `http_status`, `server_code`, `request_id`, `correlation_id`, `release`, `environment`. 401/403/422 invalid credentials warning/info; DB, timeout, unexpected, 5xx error.

## Diagnose by request ID

1. Capture iOS-sent `X-Request-ID` and response `X-Correlation-ID`.
2. In Sentry select `environment:production`; search `request_id:<value>` or `correlation_id:<value>`.
3. Inspect `server_code`, `auth_phase`, `auth_endpoint`, exception, timestamp.
4. Match hosting logs on both IDs.

Common codes: `APPLE_TOKEN_INVALID`, `APPLE_NONCE_INVALID`, `AUTH_DATABASE_ERROR`, `AUTH_SESSION_ISSUE_FAILED`, `REFRESH_TOKEN_EXPIRED`, `REFRESH_DATABASE_ERROR`, `LOGOUT_DATABASE_ERROR`, `AUTH_UPSTREAM_TIMEOUT`, `INTERNAL_SERVER_ERROR`.

## iOS verification

Send unique UUID in `X-Request-ID` on `POST /v1/auth/apple`; trigger test login; record HTTP status, JSON `code`/`message`, sent request ID, and `X-Correlation-ID`; search both IDs in Sentry; verify matching tags/log. Never attach token values.

Run tests with `pytest -q`.
