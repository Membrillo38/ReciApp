# ReciApp API

Backend: extract recipes from TikTok / YouTube / Instagram / Facebook.

- **Cache** by normalized URL (no duplicate OpenAI calls)
- **Postgres** on the VPS (users, recipes, usage)
- **Free:** 1 recipe / week
- **Pro:** unlimited with fair-use (keep ≥20% margin)
- **Admin:** `/dashboard` — users, recipes, jobs, usage, Postgres size

## Stack

- FastAPI + Docker on the VPS (Coolify)
- Self-hosted Postgres (`reciapp-postgres`)
- OpenAI: `gpt-4o-mini` + `gpt-4o-mini-transcribe`

## Docs for iOS

See **[INTEGRACION_SWIFT.md](INTEGRACION_SWIFT.md)** and the complete [Swift client](docs/swift/ReciAppAPI.swift).

## Local

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

## Deploy

This repo is the API image (`Dockerfile`). VPS host ops (Traefik, Homepage, Fail2ban, compose) live in sibling `~/Desktop/Server`.

Schema: `psql "$DATABASE_URL" -f migrations/001_init.sql` then `002_row_level_security.sql`, `003_free_yearly_limit.sql`, `004_apple_provider_tokens.sql` and `005_pro_monthly_default.sql`. Health: `/health`. Ready: `/ready`.

For a bounded recipe verification matrix, set `API_KEY` and `AUTH_JWT_SECRET` and run `scripts/e2e_matrix.sh`.

## Quotas

| Plan | Limit |
|------|-------|
| Free | 1 import / week (UTC) |
| Pro | Cache misses until monthly cost ≥ budget (`profiles.pro_monthly_price_cents × (1 - margin)`). Webhook monthlyizes weekly×52/12 and yearly÷12 into that field. Defaults in `app_settings`. |

## Verification

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```
