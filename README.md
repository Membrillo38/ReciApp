# ReciApp API

Backend: extract recipes from TikTok / YouTube / Instagram / Facebook.

- **Cache** by normalized URL (no duplicate OpenAI calls)
- **Supabase** Auth + Postgres (users, recipes, usage)
- **Free:** 1 recipe / week
- **Pro:** unlimited with fair-use (keep ≥20% margin)
- **Admin:** create / list / delete users, see recipes / jobs / usage

## Stack

- FastAPI + Docker on Render
- Supabase project `ReciApp` (`nzimdcjxgklopythnpfi`)
- OpenAI: `gpt-4o-mini` + `gpt-4o-mini-transcribe`

## Docs for iOS

See **[INTEGRACION_SWIFT.md](INTEGRACION_SWIFT.md)** and the complete [Swift client](docs/swift/ReciAppAPI.swift).

## Local

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill OPENAI + SUPABASE_SERVICE_ROLE_KEY
uvicorn app.main:app --reload --port 8000
```

## Deploy Render

1. Connect this GitHub repo
2. Docker, plan **Free** (current deployment; no paid worker)
3. Set env vars from `.env.example` (especially `SUPABASE_SERVICE_ROLE_KEY` from Supabase → Settings → API)
4. Health: `/health`

Before deploying the server, apply every pending Supabase migration. The API currently
expects migrations `005`–`013`, including translations, structured recipe sections,
TikTok photo-carousel images, language-safe translation concurrency indexes, and
durable extraction leases, database advisor hardening, and legacy error redaction. Apply and verify them against the live schema before
shipping the matching server build.

```bash
supabase link --project-ref nzimdcjxgklopythnpfi
# Inspect migration history before applying any pending migration.
supabase migration list
```

The web service uses request-local `BackgroundTasks`. `render.worker.yaml` is
intentionally empty: no paid worker is provisioned. Keep `WORKER_ENABLED=false`.
A restart can interrupt running imports; persisted jobs support status/recovery,
but this free configuration does not guarantee durable execution.

Live migrations have historical timestamp versions for files 005–013. Compare
migration names and live schema before applying SQL; do not blindly replay those
files because their local prefixes differ from the recorded versions.

## Render keep-alive (Free tier)

Free web services spin down after **15 minutes** without traffic. This repo includes a GitHub Action (`.github/workflows/render-keep-alive.yml`) that pings `/health` every **10 minutes** (buffer before timeout).

- Runs automatically on `main` once pushed to GitHub (Actions enabled).
- Optional repo variable `RENDER_HEALTH_URL` (default `https://reciapp-4ih5.onrender.com/health`).
- Set repo variable `KEEP_ALIVE_ENABLED=false` to disable.
- **Starter ($7) does not spin down** — disable or delete the workflow if you use paid.

GitHub schedules can be delayed; this workflow does not guarantee uptime.

Manual run: GitHub → Actions → **Render keep-alive** → Run workflow.

For a bounded recipe verification matrix, set the server credentials in the shell
and run `scripts/e2e_matrix.sh`. It tests the four supplied TikTok URLs, repeated
cache requests, Spanish translation handoff, and terminal job polling. It prints
only status/cache/job/progress/recipe/language/carousel counts. The matrix can
invoke OpenAI on cache misses, so run it deliberately rather than from CI.

## Quotas

| Plan | Limit |
|------|-------|
| Free | 1 import / week (UTC) |
| Pro | Cache misses until monthly cost ≥ budget (`profiles.pro_monthly_price_cents × (1 - margin)`). Defaults in `app_settings` ($4.99 → ~$3.99). Superwall webhook sets price per user on subscribe. |

## Schema

`supabase/migrations/001_init.sql` (already applied to project ReciApp).

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

GitHub Actions runs backend tests on Python 3.12. Tests requiring the ignored
`IosAPP/` directory skip in backend-only checkouts. Public readiness is `/ready`;
for authenticated verification use `scripts/authenticated_readiness.py` as
described in the Swift integration guide.
