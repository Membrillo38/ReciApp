# ReciApp: conexión fiable y reinicio preparado

Fecha: 2026-09-08. Fuente: `~/Downloads/PLAN.md`, contrastado con el código en `776158c` y las dos primeras tareas de Todoist del proyecto Recipe App.

## Alcance y prioridades

La tarea «Acabar el plan de GPT-6 Astra» pide revisar el plan y la app. «Ejecutar el plan» autoriza implementar y subir commits a GitHub, **sin subir iOS ni desplegar en Render**. Estas restricciones prevalecen sobre las instrucciones operativas del documento adjunto.

Se entrega código probado, app local y procedimiento operativo verificable. El despliegue, el backup de producción, su ensayo de restauración, el borrado y las pruebas contra el nuevo backend desplegado quedan en una fase posterior: el reset exige desplegar primero la corrección y el mantenimiento. No se cambiarán datos, configuración ni facturación remotos durante esta ejecución.

## Global Constraints

- No Render deployments, no production data mutations, no paid services, no commits or uploads of `IosAPP/`, secrets, local caches, backups or credentials.
- Push backend/docs/tests only to `codex/connection-reset-plan`; do not push or merge main, avoiding its automatic deployment.
- Preserve existing user edits. iOS changes stay at `/Users/andrescasillas/Desktop/ReciApp/IosAPP`; backend work is isolated in `/private/tmp/reciapp-connection-plan`.
- Preserve public API contracts, request/correlation IDs, server quota and spend protections, source attribution and ingredient order. Subscription SDK failure must not block library or folders or bypass server quotas.
- Keep current six locales, iOS 17.0, bundle ID `com.membri.reciapp`, folder-first UI, solid surfaces and no decorative borders or Liquid Glass. Full App Store localization and new recipe sharing are separate Todoist tasks.
- Never equate a build, mocked test, health response or old report with live end-to-end proof. Record unverified acceptance conditions explicitly.

## Diagnóstico revisado

`_StablePostgrestClient.create_session()` ignores both `base_url` and `headers`: requests are relative and authenticated PostgREST context is lost. The existing transport test checks HTTP/2 internals but never sends a real SDK request. Replace it with a transport-level request contract.

`current_user()` creates missing profiles during reads and classifies every Auth exception as 401. Superwall can recreate missing profiles after an update returns no rows. `/health` currently logs to Supabase synchronously, so even liveness can wait on the broken dependency. Maintenance must suppress all these indirect writes, workers and queued import work as well as POST/PATCH/DELETE routes.

iOS v2 snapshots include folders per user/language, but legacy category keys are global, account transitions lack stale-response protection, refresh runs library then profile, and session refresh is not coalesced. Detail cache returns without revalidation. These paths require behavioral tests, including account/language switches while requests are running.

TikTok carousel extraction and ingredient sections already exist. Verify and repair their loss cases instead of replacing the pipeline. Existing 12-slide and OCR cost bounds must never silently claim a full recipe from truncated slides.

## Task 1: Backend connection, auth and maintenance

Work in `/private/tmp/reciapp-connection-plan`. Own `app/db.py`, `app/config.py`, `app/auth.py`, `app/main.py`, `app/superwall.py`, `app/worker.py`, targeted maintenance guards in `app/pipeline.py`, `requirements.txt`, `render.yaml`, and backend tests. Do not edit local iOS. Do not deploy, push, mutate remote services or spawn subagents.

1. Reproduce the broken SDK request using a recording transport. Pin `supabase==2.31.0`, use public `create_client`/`ClientOptions`, remove all private Supabase imports and subclasses. Use a transport with one controlled retry only for genuine transient transport errors: retry safe reads; never replay an ambiguous mutation after a response/read failure. Preserve base URL and SDK authorization/schema headers. Disable session persistence/auto refresh for the service client, bound timeouts and close owned clients appropriately.
2. Validate configuration at startup: HTTPS root Supabase URL, no userinfo/query/fragment/path/whitespace, expected host (`SUPABASE_EXPECTED_HOST`), nonempty service key, compatible modern secret keys or legacy JWT with service_role and matching project ref. Error text must never include key contents. Permit explicit localhost development only if securely scoped. Validate client construction during startup without making liveness require a successful remote connection. Update `.env.example` if present with safe placeholders.
3. `/health` stays pure liveness with no Supabase reads/writes. Add `/ready`: bounded Supabase probe, status/latency only, 200 on success, 503 on failure with redacted error class; maintenance status included. Avoid blocking the event loop or leaving unbounded background probes. No DB request logging on health/readiness.
4. Make `current_user` strictly read-only: missing/soft-deleted user/profile gets denied and is never recreated; invalid credentials are 401, Auth transport/service outages 503, not logout-inducing 401. Retain server-side get_user verification. Remove profile creation fallbacks outside the DB auth trigger, including admin create path if applicable.
5. Superwall must ignore absent/deleted profiles without upsert, handle deletion races on conditional update, preserve signature validation, event idempotency and ordering. Do not allow a retry of a previously failed event to be silently mistaken for successfully processed. Test existing-user, absent-user, deleted-user, replay and failure/retry cases.
6. Add `MAINTENANCE_MODE=false`. While enabled reject all writes/imports/webhooks with retriable 503 and preserve correlation headers; leave `/health` and `/ready` available. Read routes that create translation jobs or attach recipes must not mutate. Suppress DB metrics/audits under maintenance. Worker must not claim/process new jobs; queued background extraction must check before beginning paid/DB work. Document that maintenance is activated on every writer and all in-flight jobs must drain before backup/reset; do not promise cancellation of already-running external requests.
7. Update Blueprint to `plan: free`, `/health`, `SUPABASE_EXPECTED_HOST`, bounded readiness timeout and `MAINTENANCE_MODE=false`. Use `autoDeployTrigger: off` if supported by current official Blueprint docs; document actual service is unchanged. Preserve other settings and secrets.
8. Test real SDK REST/Auth request URLs/headers, read retry bound, no ambiguous write retry, invalid config startup, liveness without DB, readiness failure/timeout, missing/deleted profile, Auth outage, maintenance on write and side-effecting GET/background/worker, signed webhook/idempotency and existing API contract. Update obsolete `_StableSupabaseClient` test; preserve existing user test from `/private/tmp/reciapp-connection-evidence/original-test_reliability_contract.py` when editing that file. Tests must also work in a backend-only checkout without ignored iOS sources (skip iOS static checks explicitly when unavailable).

Verification: use a task-local venv with pinned dependencies; focused tests then complete backend suite and `pip check`. No production writes. Record exact commands/results in task report; commit only Task 1 files. Base before work: `776158c`.

## Task 2: Local iOS cache, refresh and session correctness

Edit local iOS under `/Users/andrescasillas/Desktop/ReciApp/IosAPP` only, plus relevant tests/docs in isolated backend worktree. Read and apply iOS skills. Do not upload/commit iOS, do not deploy, no remote writes, no subagents. Save copies of changed local Swift files under `/private/tmp/reciapp-connection-evidence/ios-before` before edits.

1. Introduce v3 cache per user and canonical language; one-time remove known v1/v2 recipe caches and global legacy folder/color assignments. Folder metadata must be isolated by user and shared across languages for that user; no title/color leakage to another account. Counts remain derived. Every remote recipe without valid assignment appears in `Uncategorized`.
2. Activate cache synchronously on session/language change before network work. Show cached library/details immediately then revalidate in background. Revalidate detail once per resource; preserve cached data on transient error. Empty server success should correctly represent an empty library, but malformed/empty response body must not erase it.
3. Use shared awaitable tasks per library, profile and detail identity; concurrent calls await same work rather than starting duplicates or merely skipping the caller's completion. Library/profile begin independently and concurrently; subscription refresh joins the same profile task. Foreground cooldown is 30 seconds, while explicit refresh/import completion can force a refresh. Bound shared reconnect backoff with jitter, preserve cancellation, avoid duplicate `/v1/me` storms.
4. Attach user/language generation to all asynchronous results and progress callbacks; sign-out, deletion and account/language switches cancel pending work and reject stale results, including detail and import. Clear departing-user cache on sign-out/session invalidation; next account starts clean. Shared 401 recovery refreshes session at most once per rejected token. Failed auth refresh or a repeated 401 clears that user's state and returns to login; transient initial restore failure must not turn a valid offline cached session into a false logout. Logout must be local even when offline.
5. API retry/backoff must be cancellable and must not repeat unsafe mutation merely because of 502/503/504. Existing normalized extraction job dedup and quotas remain enforced. Handle maintenance as transient service unavailability. UUID Superwall identity, `free_limit_reached`, purchase restore and errors remain independent of recipes; do not alter live paywall configuration.
6. Keep ingredient section titles/order and one flat fallback section without loss or duplicates. Test and adjust the local model/render boundary if needed; no UI redesign.
7. Add runnable local behavioral tests for cache isolation/legacy cleanup, unassigned recipes, language/account switch, stale response rejection, concurrent refresh/401 recovery, foreground cooldown, offline cached detail/revalidation and ingredients. Prefer small dependency injection at existing boundaries over production-only abstractions or string assertions. Keep local harness/source/tests out of Git if they include app implementation. Update obsolete backend static iOS checks to current behavior and skip them explicitly in backend-only checkout.

Verification: build app plus Share Extension with xcodebuild/XcodeBuildMCP, run meaningful local tests, inspect already available simulator UI and logs if possible. Do not erase a simulator or uninstall existing user app. Record build versus runtime proof separately; iPhone/Apple login, paid purchase and live new-backend tests deferred. Commit only backend test/doc adjustments, never iOS or a diff containing its code.

## Task 3: Extraction completeness and reset runbook

Work in `/private/tmp/reciapp-connection-plan`. Own `app/tiktok_slides.py`, extraction/ingredient repair sites only as needed, targeted extraction tests, `scripts/`, reset/readiness runbooks and final plan updates. Do not deploy, reset, create users, perform paid extraction, upload iOS or spawn subagents.

1. Review existing video audio/caption/frame pipeline, carousel hydration variants and per-image OCR order. Preserve all available ordered slides inside current spend limits. If a carousel exceeds supported bound or a slide cannot be read, return an explicit incomplete/unsupported extraction failure; do not silently truncate or report full coverage from an OG cover. Do not remove cost limits. Preserve normalized URL dedup plus recipe source fingerprint used by translations; do not merge different videos just because a superficial content hash matches.
2. Prove ingredient sections preserve order/titles and flatten without omission/duplication. Reuse existing contract tests; add focused failure-case tests only for actual gaps. Four known input URLs are already in `scripts/e2e_matrix.sh`; include those in deferred live acceptance, without running production mutations.
3. Produce a complete operator runbook and narrowly scoped scripts for a later safe reset. Preflight must be read-only by default, with explicit target host/ref and table allowlist. Require all writer services in maintenance, zero active leases/jobs and no in-flight process before consistent snapshot. PostgreSQL 17 client, TLS, credentials via environment/service files (never shell args/log output), public/auth plus migration/schema preservation evidence. Capture exact table counts and consistent snapshot identifiers; include `app_settings` and schema/migration fingerprints.
4. Backup to `~/Documents/ReciApp Backups/` only during later approved run. Specify/generate AES-256 encrypted backup with password from macOS Keychain, SHA-256, restrictive permissions, and no plaintext leftovers. Auth schema alone is not a complete Supabase restore: roles/extensions/custom policies/storage metadata/config dependencies must be accounted for. No real backup or Keychain writes in this task.
5. Restoration rehearsal into a disposable PostgreSQL 17 target must validate decryptability, restore exit status, counts and preserved schema/settings/migration values. A hash/list check alone is insufficient. A reviewed receipt tied to exact encrypted backup digest and target project gates reset.
6. Reset script must default to dry-run or transaction rollback, require explicit execute confirmation, verified rehearsal receipt and target identity, and operate in one transaction with exact allowlisted tables. Never use unbounded `CASCADE`. Delete auth users with dependent identities/sessions/tokens accounted for. Abort on unknown dependent tables or nonempty Storage; never bypass Storage API. Preserve `app_settings` and schema objects/migrations; verify zero target data before commit. No destructive script is executed in this task.
7. Old JWT rejection test belongs after reset using new backend. Existing auth tokens may still pass signature checks: strict server get_user plus profile existence prevents access; direct Supabase RLS/session behavior must be checked separately, not overclaimed. If restoration needed keep maintenance active, restore the verified backup, validate consistency before opening traffic. Treat restore as a controlled operation, never automatic retry after ambiguous reset commit.
8. Add a read-only authenticated acceptance runner: `/health`, `/ready`, 100 library/profile cycles, request IDs and latency p95, no token/body logging. Do not run remote write/import matrix before deployment. Define the manual 20 foreground/relaunch cycles, network transitions, Apple creation, folder CRUD, each supplied recipe, dedup, free limit/paywall/restore with explicit pass/fail criteria. Performance goals: cached library <=250 ms, detail skeleton <=100 ms, hot library p95 <=800 ms, import job creation <=1 s. Record as targets until measured.

Verification: test reset guards/allowlists/receipt validation on synthetic fixtures and mocked command execution; validate shell/Python syntax and runner redaction. Run combined backend suite once after changes. Commit Task 3 code/docs. Final report lists exact passed checks, local iOS changes without source upload, deferred operational gates and branch/commit links.

## Entrega final

Revisión independiente de código completo y corrección de hallazgos. Comprobar que el índice/commits excluyen iOS, secretos, `.env`, backups y `supabase/.temp/`. Subir únicamente la rama autorizada, verificar su SHA remoto y actualizar Todoist cuando sus requisitos de entrega estén comprobados. No marcar como probadas las fases operativas diferidas.

## Fuentes consultadas

- [Supabase Python 2.31.0](https://github.com/supabase/supabase-py/releases/tag/v2.31.0).
- [Inicialización pública del cliente Python](https://supabase.com/docs/reference/python/initializing).
- [Render: instancia gratuita](https://render.com/docs/free).
- [Render Blueprint specification](https://render.com/docs/blueprint-spec).
