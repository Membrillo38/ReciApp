# ReciApp security runbook

## Security boundary

- `API_KEY`, `OPENAI_API_KEY`, `AUTH_JWT_SECRET`, dashboard secrets and webhook secrets stay on the VPS. Never put them in iOS, logs, CI output or dashboard responses.
- The admin `API_KEY` is server-only.

## Deploy order

1. Apply `migrations/001_init.sql` on self-hosted Postgres. Keep `WORKER_ENABLED=false` until a worker is authorized.
2. Set `DASHBOARD_TOTP_SECRET`, `DASHBOARD_SESSION_SECRET`, `BILLING_GUARD_ENABLED=true` and budget variables on the VPS.
3. Configure Apple App Store Server Notifications V2 at `/v1/webhooks/apple` with `APPLE_ROOT_CA_PEM`.
4. Configure Superwall webhook signing. Unsigned events are rejected.
5. Configure provider-side spend limits and alerts at 50%, 75%, 90% and 100%.
6. Deploy the web service and run `/health`, `/ready`, then the recipe matrix with `AUTH_JWT_SECRET`.

## Operator controls

- Kill switch: set `BILLING_GUARD_ENABLED=false` only to deliberately stop protected extraction; the API fails closed with `503`.
- Daily/monthly/user budgets: `DAILY_API_BUDGET_CENTS`, `MONTHLY_API_BUDGET_CENTS`, `USER_MONTHLY_BUDGET_CENTS`.
- Dashboard requires password, session secret and TOTP.

## Data lifecycle and recovery

- Encrypted Postgres backups on the VPS (`deploy/postgres-backup.sh`). Test restore on a disposable database.
- Account deletion revokes the profile and leaves only the minimum redacted billing/audit record.
