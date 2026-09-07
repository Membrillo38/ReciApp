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

See **[IOS_INTEGRATION.md](IOS_INTEGRATION.md)** — pass that file to the app.

## Local

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill OPENAI + SUPABASE_SERVICE_ROLE_KEY
uvicorn app.main:app --reload --port 8000
```

## Deploy Render

1. Connect this GitHub repo
2. Blueprint / Docker, plan **Starter** ($7 always-on) or Free
3. Set env vars from `.env.example` (especially `SUPABASE_SERVICE_ROLE_KEY` from Supabase → Settings → API)
4. Health: `/health`

Before deploying the server, apply every pending Supabase migration. The API currently
expects migrations `005`–`013`, including translations, structured recipe sections,
TikTok photo-carousel images, language-safe translation concurrency indexes, and
durable extraction leases, database advisor hardening, and legacy error redaction. Apply and verify them against the live schema before
shipping the matching server build.

```bash
supabase link --project-ref nzimdcjxgklopythnpfi
supabase db push
```

The web service uses request-local `BackgroundTasks` by default. A separate
`render.worker.yaml` defines the optional `reciapp-extract-worker`; deploy it only
after migration `011` is live, then set `WORKER_ENABLED=true` on both web and worker
at the same cutover. The worker claims jobs with Postgres `SKIP LOCKED` leases and
recovers claims after a restart. It is a paid Render service, so do not activate it
without a cost decision.

## Render keep-alive (Free tier)

Free web services spin down after **15 minutes** without traffic. This repo includes a GitHub Action (`.github/workflows/render-keep-alive.yml`) that pings `/health` every **10 minutes** (buffer before timeout).

- Runs automatically on `main` once pushed to GitHub (Actions enabled).
- Optional repo variable `RENDER_HEALTH_URL` (default `https://reciapp-4ih5.onrender.com/health`).
- Set repo variable `KEEP_ALIVE_ENABLED=false` to disable.
- **Starter ($7) does not spin down** — disable or delete the workflow if you use paid.

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
