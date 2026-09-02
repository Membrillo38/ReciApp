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

## Quotas

| Plan | Limit |
|------|-------|
| Free | 1 import / week (UTC) |
| Pro | Cache misses until cost ≈ 80% of `PRO_MONTHLY_PRICE_CENTS` (default $4.99 → $3.99 budget) |

## Schema

`supabase/migrations/001_init.sql` (already applied to project ReciApp).
