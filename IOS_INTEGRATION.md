# ReciApp — iOS Integration Guide

Pass this file to the iOS agent / engineer. Backend lives on Render; auth + DB on Supabase.

## 1. Services

| Service | Role | Value |
|---------|------|-------|
| **Render API** | Extract recipes, quotas, admin | `https://<your-service>.onrender.com` |
| **Supabase** | Auth (Sign in with Apple) + Postgres | `https://nzimdcjxgklopythnpfi.supabase.co` |
| **Supabase anon key** | iOS only (never service_role) | see dashboard / below |

**Project ref:** `nzimdcjxgklopythnpfi`  
**Region:** `eu-west-1`

Publishable / anon (iOS):

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im56aW1kY2p4Z2tsb3B5dGhucGZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNjE1ODksImV4cCI6MjEwMzkzNzU4OX0._7_828Cs63M7tWLT83DYmtpAYP_8ptDg2Gr_4hRdzGM
```

Also: `sb_publishable_qSC1aaMwrYjf2d8tbrHccw_zSw-kZev`

**Do not put `service_role` in the app.**

## 2. App env / Info.plist

```
RECIPAPP_API_BASE_URL=https://reciapp-4ih5.onrender.com
SUPABASE_URL=https://nzimdcjxgklopythnpfi.supabase.co
SUPABASE_ANON_KEY=<anon key above>
```

After first Render deploy, replace `RECIPAPP_API_BASE_URL` with the real URL.

## 3. Auth flow (iOS)

1. Sign in with Apple → identity token.
2. Supabase Swift SDK: `signInWithIdToken(provider: .apple, idToken: ...)`.
3. Read `session.accessToken`.
4. All API calls:

```
Authorization: Bearer <accessToken>
Content-Type: application/json
```

Enable Apple provider in Supabase Dashboard → Authentication → Providers.

## 4. Core user API

### Health

```
GET {API}/health
→ { "status": "ok" }
```

### Me + quota

```
GET {API}/v1/me
Authorization: Bearer …

→ {
  "id": "uuid",
  "email": "...",
  "display_name": "...",
  "is_pro": false,
  "pro_expires_at": null,
  "free_used_this_week": 0,
  "free_limit": 1,
  "free_remaining": 1,
  "pro_cost_cents_this_month": 0,
  "pro_budget_cents": 399.2,
  "pro_remaining_cents": 399.2
}
```

### Delete account

```
DELETE {API}/v1/me
```

### Extract recipe

```
POST {API}/v1/extract
{ "url": "https://www.tiktok.com/@x/video/123" }

→ { "job_id": "uuid", "status": "pending"|"completed", "cache_hit": true|false }
```

Poll:

```
GET {API}/v1/jobs/{job_id}

→ {
  "job_id": "...",
  "status": "pending"|"processing"|"completed"|"failed",
  "cache_hit": false,
  "cost_cents": 0.4,
  "recipe": { ... } | null,
  "error": null
}
```

Poll every 2s until `completed` or `failed`. Cache hit returns `completed` immediately.

### My recipes

```
GET {API}/v1/me/recipes
→ { "items": [ { recipe fields..., "saved_at": "..." } ] }

DELETE {API}/v1/me/recipes/{recipe_id}
→ { "ok": true }
```

### Recipe detail

```
GET {API}/v1/recipes/{recipe_id}
```

Only if saved by that user.

## 5. Recipe JSON shape

```json
{
  "id": "uuid",
  "title": "Brownies",
  "ingredients": [{ "name": "cacao", "quantity": "2", "unit": "cda" }],
  "steps": [{ "order": 1, "text": "Mezcla…", "duration_minutes": null }],
  "servings": 4,
  "prep_minutes": 10,
  "cook_minutes": 20,
  "tags": ["postre"],
  "confidence": 0.85,
  "missing_fields": [],
  "source_url": "https://...",
  "platform": "tiktok",
  "thumbnail_url": "https://...",
  "author": "chef",
  "description": "...",
  "raw_transcript": "..."
}
```

`platform`: `tiktok` | `youtube` | `instagram` | `facebook` | `unknown`

## 6. Quotas (show in UI)

| Plan | Rule |
|------|------|
| **Free** | 1 import / calendar week (UTC Mon–Sun). Hit or miss counts. |
| **Pro** | Unlimited imports; **cache miss** blocked if monthly OpenAI cost ≥ budget (`pro_monthly_price_cents × (1 - margin)`). Cache hits always free. |

Limits live in **Supabase** (`app_settings` defaults + per-user `profiles` columns). On subscribe, Superwall webhook writes `pro_monthly_price_cents` from the purchase price. Default Pro: **$4.99/mo** → budget **~$3.99** cost/month.

### Error bodies (HTTP 403)

```json
{
  "detail": {
    "code": "FREE_WEEKLY_LIMIT",
    "message": "Free plan: 1 recipe per week. Upgrade to Pro.",
    "free_used_this_week": 1,
    "free_limit": 1
  }
}
```

```json
{
  "detail": {
    "code": "PRO_FAIR_USE_LIMIT",
    "message": "Pro fair-use limit reached this month (keeps 20% margin).",
    "pro_cost_cents_this_month": 400,
    "pro_budget_cents": 399.2,
    "pro_monthly_price_cents": 499
  }
}
```

UI: on `FREE_WEEKLY_LIMIT` → paywall. On `PRO_FAIR_USE_LIMIT` → soft message (try cached links / wait next month).

### Superwall → Pro (already wired)

Backend endpoint:

```
POST https://reciapp-4ih5.onrender.com/v1/webhooks/superwall
```

Superwall project **40844**, application **54783**, webhook URL above.

**Required in iOS after Supabase login:**

```swift
Superwall.shared.identify(userId: supabaseUserId.uuidString)
Superwall.shared.setUserAttributes(["supabase_user_id": supabaseUserId.uuidString])
```

Without this, webhook cannot map purchase → `profiles.is_pro`.

Events:
- `initial_purchase` / `renewal` / `uncancellation` → `is_pro = true`
- `expiration` → `is_pro = false`
- `cancellation` → keeps Pro until `expirationAt`

Public API key (SDK): `pk_3QyV6dXg2nPMj9gDTpZkF`

### Mark Pro manually (admin)

```
PATCH {API}/v1/admin/users/{user_id}
X-API-Key: <API_KEY from Render>
{ "is_pro": true, "pro_expires_at": "2026-10-02T00:00:00Z" }
```

## 7. Suggested Swift models

```swift
struct ExtractRequest: Encodable { let url: String }
struct ExtractJobResponse: Decodable {
  let jobId: UUID
  let status: String
  let cacheHit: Bool
  enum CodingKeys: String, CodingKey {
    case jobId = "job_id", status, cacheHit = "cache_hit"
  }
}
```

Use `JSONDecoder` with `.convertFromSnakeCase` for the rest.

## 8. Share Extension

1. Receive URL from TikTok / YouTube / IG.
2. Open main app with URL (or call extract with stored token).
3. Same `POST /v1/extract`.

## 9. Admin (not for App Store client)

Header: `X-API-Key: <Render API_KEY>`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/admin/users` | list users |
| POST | `/v1/admin/users` | create user `{email,password?,is_pro?}` |
| PATCH | `/v1/admin/users/{id}` | set pro / name |
| DELETE | `/v1/admin/users/{id}` | delete user |
| GET | `/v1/admin/recipes` | all cached recipes |
| GET | `/v1/admin/jobs` | all jobs |
| GET | `/v1/admin/usage` | cost events |

## 10. Cache behavior

Same video URL (normalized) → **no OpenAI call**. Instant job `completed` + `cache_hit: true`. Still counts for Free weekly limit.

## 12. Admin dashboard (solo tú)

URL: `{API}/dashboard`

Protección:
- Password env `DASHBOARD_PASSWORD` (solo tú la sabes)
- Cookie `HttpOnly` + `Secure` + `SameSite=Strict`
- CSRF en acciones POST
- `noindex`
- Sin password → login disabled

Pestañas: Overview (gastos API, requests), Users (make/revoke Pro, delete), Recipes cache, Jobs, Usage, HTTP requests.

Set en Render: `DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET`.


- [ ] Render service deployed, `/health` OK
- [ ] Env: `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `API_KEY`, `SUPERWALL_WEBHOOK_SECRET`
- [ ] Supabase Apple Sign In configured
- [ ] Superwall `identify(supabaseUserId)` after login
- [ ] iOS has anon key + API base URL + Superwall `pk_3QyV6dXg2nPMj9gDTpZkF`
- [ ] Handle `FREE_WEEKLY_LIMIT` / `PRO_FAIR_USE_LIMIT`
- [ ] `DASHBOARD_PASSWORD` set → `/dashboard` works for you only
