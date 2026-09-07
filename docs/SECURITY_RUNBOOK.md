# ReciApp security runbook

## Security boundary

- `API_KEY`, `OPENAI_API_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_ANON_KEY` and the public Superwall key are unchanged.
- The admin `API_KEY` is server-only. `IosAPP/ReciApp/Config/Secrets.swift` is ignored and is no longer part of the Xcode target. Its historical Git exposure remains a critical accepted risk until rotation is explicitly authorized.
- `SUPABASE_SERVICE_ROLE_KEY` is only loaded by the Render server. It must never be added to the iOS target, logs, CI output, Blueprints or dashboard responses.

## Deploy order

1. Apply migrations `005` through `013` to staging, then production. Keep `WORKER_ENABLED=false` while validating the web deploy.
2. Configure `DASHBOARD_TOTP_SECRET`, `DASHBOARD_SESSION_SECRET`, `BILLING_GUARD_ENABLED=true` and the budget variables in Render.
3. Configure Apple App Store Server Notifications V2 with the signed payload endpoint `/v1/webhooks/apple` and the pinned Apple root certificate in `APPLE_ROOT_CA_PEM`.
4. Configure Superwall webhook signing and keep `SUPERWALL_WEBHOOK_SECRET` non-empty. Unsigned events are rejected.
5. Configure provider-side hard spend limits and alerts at 50%, 75%, 90% and 100%. The server-side reservation is an additional guard, not a replacement.
6. Deploy the web service and run the read-only health/schema plus recipe matrix checks.
7. If durable jobs are desired, deploy `render.worker.yaml`, set `WORKER_ENABLED=true` on both services at the same cutover, and verify one extraction plus one translation job. The worker is a separate paid Render service.
8. Deploy the iOS app. Rollback is safe because migrations are additive and old API routes remain.

## Operator controls

- Kill switch: set `BILLING_GUARD_ENABLED=false` only to deliberately stop protected extraction; the API fails closed with `503`.
- Daily/monthly/user budgets: `DAILY_API_BUDGET_CENTS`, `MONTHLY_API_BUDGET_CENTS`, `USER_MONTHLY_BUDGET_CENTS`.
- Concurrency: `MAX_CONCURRENT_JOBS` and `MAX_CONCURRENT_JOBS_PER_USER`.
- Dashboard requires password, session secret and TOTP. Login attempts are rate-limited; mutations require CSRF.

## Data lifecycle and recovery

- Keep transcripts for 30 days, request IP pseudonyms for 14 days, and billing payloads only for reconciliation/legal needs. Add scheduled deletion policies before production data grows.
- Enable Supabase PITR and encrypted external backups on the selected plan. Test a staging restore monthly and record RPO <= 15 minutes and RTO <= 4 hours.
- Account deletion revokes the profile, cascades owned relations, removes personal profile data and leaves only the minimum redacted billing/audit record needed for reconciliation.

## Security validation gate

- Build iOS and assert the admin key is absent from the app target/binary.
- Verify A cannot read B's jobs/recipes.
- Send unsigned, duplicate, stale and out-of-order Superwall events; only the first signed current event may alter entitlement.
- Send unsigned Apple JSON and invalid JWS; both must fail closed.
- Run 20 concurrent extraction requests, exhaust daily budget, and repeat one normalized URL.
- Probe private IPs, metadata endpoints, unsafe redirects and oversized payloads.
- Exercise dashboard brute force, invalid TOTP, CSRF and expired session.
- Review logs for absence of tokens, cookies, authorization headers and API keys.
