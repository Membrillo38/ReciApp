# ReciApp production reset runbook

Status: prepared only. Nothing in this runbook was executed against production. The current local PostgreSQL tools are version 14; install and select PostgreSQL 17 before any approved run.

## Safety boundary

This procedure deletes all ReciApp user, recipe, job, usage, subscription-event and Auth runtime data. It preserves `public.app_settings`, database schema and migration history, Auth provider/OAuth client definitions and Storage. It refuses nonempty Storage because Storage objects must be removed through the Storage API, never by deleting `storage.objects` rows.

The operator must keep maintenance and every external writer frozen continuously from preflight through backup, rehearsal approval and reset. A FastAPI `MAINTENANCE_MODE=true` flag alone is insufficient: Supabase Auth signup/session refresh, direct Data API clients, database cron, Render workers, queued/background requests and every service-role client can still write. Do not begin until all in-flight external requests have drained. Maintenance does not cancel requests already running.

Never pass passwords, database URLs, service keys, access tokens or backup passwords as command arguments. Use a restrictive PostgreSQL service file or `PGHOST`, `PGUSER`, `PGDATABASE`, `PGPASSWORD` and `PGSSLMODE=verify-full` in the operator environment. Command output and receipts must contain counts, hashes and request IDs only.

## Fixed scope

Reset scripts use exact allowlists from `scripts/reset_guard.py`. They delete rows with explicit `DELETE` statements inside one transaction. They do not use `TRUNCATE`, `CASCADE`, wildcard schema operations or Storage SQL. Any unknown public/Auth table or dependent table aborts preflight for human review.

Preserved database state includes:

- `public.app_settings` and all schema objects, functions, RLS policies and migration records.
- `auth.instances`, `auth.oauth_clients`, SAML/SSO provider definitions and `auth.schema_migrations` when present.
- Supabase migration history under `supabase_migrations`.
- Storage schema/metadata only when object count is zero.

Auth runtime deletion accounts for users, identities, sessions, refresh tokens, one-time tokens, MFA state, flow state, OAuth authorizations/consents/codes/sessions, SAML relay state, hook payloads and Auth audit entries when those tables exist. Auth provider dashboard settings, redirect/site URLs, Apple provider keys, external OAuth secrets, Render environment variables and project-level configuration are external dependencies: export their names/settings separately and verify them after rehearsal. Do not put secret values in receipts.

## 1. Deployment gate

Before this runbook can be used, deploy the reviewed backend change to every web/worker service and verify both `/health` and authenticated `/ready`. Configure `SUPABASE_EXPECTED_HOST` exactly. Confirm Render has no old instance or worker still accepting writes. This task intentionally did not deploy.

## 2. Freeze evidence

Create a mode `0600` JSON file outside the repository. Use the exact production ref and direct database host:

```json
{
  "target_ref": "nzimdcjxgklopythnpfi",
  "target_host": "db.nzimdcjxgklopythnpfi.supabase.co",
  "all_backend_instances_maintenance": true,
  "background_workers_stopped": true,
  "auth_signups_disabled": true,
  "auth_session_refresh_frozen": true,
  "direct_data_api_writers_frozen": true,
  "cron_writers_frozen": true,
  "service_role_clients_frozen": true,
  "in_flight_processes": 0,
  "reviewed_by": "operator name",
  "observed_at": "2026-09-09T12:00:00+00:00"
}
```

Attach operator evidence for every boolean: Render service list/config, zero running background requests, worker stopped, Supabase Auth signup/provider controls, paused cron jobs, revoked or stopped direct writers, and inventory of service-role clients. The file must be no older than 30 minutes. Keep the freeze active; do not edit the evidence file after preflight.

## 3. Read-only preflight

Select PostgreSQL 17 tools and a TLS service configuration, then run:

```bash
export PGHOST=db.nzimdcjxgklopythnpfi.supabase.co
export PGUSER=postgres
export PGDATABASE=postgres
export PGSSLMODE=verify-full
export PGSERVICE=reciapp-production

python3 scripts/reset_preflight.py \
  --target-ref nzimdcjxgklopythnpfi \
  --target-host db.nzimdcjxgklopythnpfi.supabase.co \
  --writer-evidence /secure/operator/writer-freeze.json \
  --output /secure/operator/preflight.json
```

Preflight uses repeatable-read, read-only transactions. It checks PostgreSQL 17, exact table inventory/FK dependencies, zero pending or processing jobs/leases, zero Storage objects, exact public/Auth row counts, snapshot identifiers, `app_settings`, Auth config, schema and migration fingerprints. Review the receipt and database/project identity before proceeding.

## 4. Encrypted backup

The Keychain item must already exist. These scripts never create or update it. During a separately approved run, `reset_backup.py` writes only under `~/Documents/ReciApp Backups/`, creates a full custom database dump plus role inventory, packages a manifest, encrypts the package with AES-256-CBC/PBKDF2, calculates SHA-256, applies restrictive permissions and removes plaintext temporary files on success or failure.

```bash
python3 scripts/reset_backup.py \
  --target-ref nzimdcjxgklopythnpfi \
  --target-host db.nzimdcjxgklopythnpfi.supabase.co \
  --writer-evidence /secure/operator/writer-freeze.json \
  --preflight /secure/operator/preflight.json \
  --keychain-service ReciApp-Reset-Backup \
  --keychain-account production
```

The counts and dump are consistent only because the proven write freeze remains continuous. Do not lift it between preflight and backup. Keep encrypted file and receipt together. Confirm no plaintext `.dump`, `.sql` or `.tar` remains in the backup directory.

## 5. Full restoration rehearsal

Provision a disposable PostgreSQL 17 target with no production network route and enough privileges for roles/extensions/schema restore. Point `PGHOST` and its remaining PostgreSQL environment variables to that disposable target. It must differ from production.

```bash
python3 scripts/reset_rehearsal.py \
  --source-ref nzimdcjxgklopythnpfi \
  --source-host db.nzimdcjxgklopythnpfi.supabase.co \
  --rehearsal-host disposable-db.internal \
  --disposable-target reciapp-reset-rehearsal-20260909 \
  --encrypted-backup "$HOME/Documents/ReciApp Backups/reciapp-....tar.enc" \
  --backup-receipt "$HOME/Documents/ReciApp Backups/reciapp-....tar.enc.receipt.json" \
  --keychain-service ReciApp-Reset-Backup \
  --keychain-account production \
  --output /secure/operator/rehearsal.json
```

The rehearsal must decrypt, restore roles and database with successful exit status, then match public/Auth counts, `app_settings`, Auth configuration, schema and migration fingerprints. Listing files or checking the encrypted hash alone does not qualify. Its receipt remains unapproved. A reviewer must inspect the disposable target, then issue a separate approval tied to that target and receipt:

```bash
python3 scripts/reset_approve_rehearsal.py \
  --receipt /secure/operator/rehearsal.json \
  --reviewed-by "operator name" \
  --expected-disposable-target reciapp-reset-rehearsal-20260909 \
  --output /secure/operator/rehearsal-approved.json
```

Use only `rehearsal-approved.json` for reset. Destroy the disposable target after the reset decision.

## 6. Reset dry run and execution

Return PostgreSQL environment variables to production. Default invocation performs current read-only guards and prints a dry-run summary; it does not issue delete statements:

```bash
python3 scripts/reset_execute.py \
  --target-ref nzimdcjxgklopythnpfi \
  --target-host db.nzimdcjxgklopythnpfi.supabase.co \
  --writer-evidence /secure/operator/writer-freeze.json \
  --preflight /secure/operator/preflight.json \
  --backup-receipt "$HOME/Documents/ReciApp Backups/reciapp-....tar.enc.receipt.json" \
  --rehearsal-receipt /secure/operator/rehearsal-approved.json
```

For a separately approved destructive run, add both `--execute` and the exact confirmation printed from the backup digest:

```text
--confirm RESET:nzimdcjxgklopythnpfi:<64-character-encrypted-backup-sha256>
```

The executor rechecks receipt integrity and chain, target identity, current writer freeze, table inventory, zero jobs/leases, empty Storage and preserved fingerprints. It locks every deletion table, deletes exact allowlisted rows, proves every target table is empty and rechecks preserved settings/Auth config/migration fingerprints before commit. A database error aborts the transaction. Treat a lost client connection after commit begins as ambiguous: inspect counts and transaction outcome manually. Never retry reset automatically.

## 7. Post-reset validation

Keep all writers frozen. Verify exact target counts are zero and preserved fingerprints match. Then deploy/restart the corrected backend, obtain a newly created test account through the intended Apple flow, and run the read-only authenticated runner with the token in the environment:

```bash
read -rs RECIAPP_ACCESS_TOKEN && export RECIAPP_ACCESS_TOKEN
python3 scripts/authenticated_readiness.py \
  --base-url https://reciapp-4ih5.onrender.com \
  --cycles 100
```

Pass criteria: `/health` 200, `/ready` 200, all 100 library and 100 profile reads return 200, no missing request IDs, and each hot library/profile p95 at most 800 ms. The runner fails closed when any criterion is missed and never prints tokens or response bodies.

Existing JWTs may still pass signature verification until expiry. Backend `get_user` plus required profile existence must reject deleted users. Separately verify direct Supabase Data API/RLS access with an old token and confirm old Auth sessions cannot refresh. Do not describe signature rejection as proven.

Before reopening traffic, manually run and record:

1. 20 foreground/background and 20 cold relaunch cycles; cached library visible within 250 ms and detail skeleton within 100 ms.
2. Wi-Fi to cellular/offline transitions; cached library/detail remains usable and reconnect produces no duplicate `/v1/me` or recipe storm.
3. Apple account creation, logout while offline, login restore and account deletion; no data crosses accounts.
4. Folder create/rename/delete/move-all and `Uncategorized` behavior.
5. Each supplied source in `scripts/e2e_matrix.sh`: three TikTok videos and one photo carousel. Confirm complete ordered evidence, bounded video-frame fallback where used, ingredients/steps, source attribution and no silent partial carousel result.
6. Repeat each source to confirm normalized URL dedup, shared extraction and translation fingerprint behavior without merging distinct videos.
7. Free-limit denial, paywall presentation, purchase/restore/cancel/error paths and Superwall identity, independent of library availability.
8. Import creation target at most 1 second, hot library p95 at most 800 ms. Record actual measurements; current numbers are targets only.

Do not run the live write/import matrix until deployment and explicit authorization.

## 8. Recovery

If validation fails, keep maintenance and all external writers frozen. Restore only the encrypted backup whose SHA-256 matches the approved rehearsal receipt. Repeat decrypt/restore/count/fingerprint validation against a controlled production recovery target. Do not open traffic until consistency is proven. Never trigger restore as an automatic retry after an ambiguous reset commit.
