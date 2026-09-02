# ReciApp — iOS App Spec

Single source of truth for the iOS app. Backend on Render; auth + DB on Supabase; subscriptions via Superwall.

---

## 1. Constants (ship in app)

| Key | Value |
|-----|-------|
| API base | `https://reciapp-4ih5.onrender.com` |
| Supabase URL | `https://nzimdcjxgklopythnpfi.supabase.co` |
| Supabase anon | see below |
| Superwall public key | `pk_3QyV6dXg2nPMj9gDTpZkF` |
| Superwall app id | `54783` |

```
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im56aW1kY2p4Z2tsb3B5dGhucGZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNjE1ODksImV4cCI6MjEwMzkzNzU4OX0._7_828Cs63M7tWLT83DYmtpAYP_8ptDg2Gr_4hRdzGM
```

**Never in app:** `service_role`, Render `API_KEY`, OpenAI keys, dashboard password.

---

## 2. Architecture — who does what

```
┌─────────┐   Sign in with Apple    ┌───────────┐
│ iOS App │ ───────────────────────►│ Supabase  │
│         │◄── JWT access_token ────│   Auth    │
└────┬────┘                           └─────┬─────┘
     │ Bearer JWT                           │ profiles (is_pro, limits)
     │                                      │
     ▼                                      ▼
┌─────────┐   service_role (server)  ┌───────────┐
│ Render  │◄────────────────────────►│ Supabase  │
│  API    │   recipes cache, usage     │ Postgres  │
└────┬────┘                            └───────────┘
     ▲
     │ Svix-signed webhook
┌────┴────┐   StoreKit + paywall UI   ┌─────────┐
│Superwall│◄──────────────────────────│ iOS App │
└─────────┘                            └─────────┘
```

| Component | Responsibility |
|-----------|----------------|
| **Supabase Auth** | Apple login → JWT. Auto-creates `profiles` row. |
| **Superwall SDK** | Paywall UI + App Store billing. Does **not** touch your DB. |
| **Render API** | Extract recipes, enforce quotas, apply Superwall webhooks → `is_pro`. |
| **Supabase DB** | Truth: `profiles`, cached `recipes`, `user_recipes`, `usage_events`. |

### Subscription flow

1. User signs in with Apple → Supabase session → `accessToken`.
2. **Immediately:** `Superwall.shared.identify(userId: supabaseUserId.uuidString)`.
3. **Immediately:** `Superwall.shared.setUserAttributes(["supabase_user_id": supabaseUserId.uuidString])`.
4. User hits free limit → show Superwall paywall.
5. User purchases Pro → Apple + Superwall handle payment.
6. Superwall sends webhook → `POST /v1/webhooks/superwall` → server sets `profiles.is_pro = true`.
7. App refreshes `GET /v1/me` → `is_pro: true`.
8. On subscription expiry webhook → `is_pro = false`.

**Critical:** without step 2–3, webhook cannot link purchase to Supabase user.

Webhook URL (already configured): `https://reciapp-4ih5.onrender.com/v1/webhooks/superwall`

---

## 3. App screens & flows

### 3.1 Launch / Auth

- If no Supabase session → Sign in with Apple.
- Supabase Swift: `signInWithIdToken(provider: .apple, idToken: ...)`.
- On success: identify Superwall (section 2), then `GET /v1/me`.

### 3.2 Home — saved recipes

- `GET /v1/me/recipes` → list of **RecipeSummary** (small payload).
- Tap row → detail screen.
- Pull to refresh.

### 3.3 Import recipe

1. User pastes URL or Share Extension sends URL (TikTok / YouTube / IG / FB).
2. `POST /v1/extract` with `{ "url": "..." }`.
3. Response: `{ job_id, status, cache_hit }`.
4. If `status == "completed"` (cache hit) → fetch recipe via job or detail endpoint.
5. Else poll `GET /v1/jobs/{job_id}` every **2s** until `completed` or `failed`.
6. On `completed` → show `recipe` from job response (RecipePublic).
7. On `failed` → show `error` string.
8. On 403 → handle quota errors (section 7).

### 3.4 Recipe detail

- Prefer recipe from completed job (already in memory).
- Or `GET /v1/recipes/{id}` if opened from home list.
- Show: title, image, ingredients, steps, times, tags, link to source video.

### 3.5 Settings / account

- Show plan: Free vs Pro from `/v1/me`.
- Pro: optional fair-use meter from `pro_remaining_cents`.
- Delete account: `DELETE /v1/me` → sign out locally.
- Restore purchases: Superwall SDK (server gets webhook on renewal).

### 3.6 Share Extension

1. Receive URL from TikTok / YouTube / Instagram.
2. Open main app with URL (App Group / deep link) **or** extract in extension if token in Keychain.
3. Same flow as §3.3.

---

## 4. HTTP client rules

Every authenticated request:

```
Authorization: Bearer <supabase accessToken>
Content-Type: application/json
```

Base URL: `https://reciapp-4ih5.onrender.com`

Token refresh: use Supabase SDK auto-refresh before calls if session near expiry.

**403 handling:** parse `detail.code` (section 7).

---

## 5. API reference (user-facing only)

### `GET /health`

No auth. `{ "status": "ok" }` — connectivity check only.

### `GET /v1/me`

Quota + plan. **No email, no internal costs.**

```json
{
  "id": "uuid",
  "display_name": "…",
  "is_pro": false,
  "pro_expires_at": null,
  "free_used_this_week": 0,
  "free_limit": 1,
  "free_remaining": 1,
  "pro_remaining_cents": null
}
```

- Free: `pro_remaining_cents` is `null`.
- Pro: number = fair-use budget left (optional UI).

### `POST /v1/extract`

Body: `{ "url": "https://…" }`

Response:

```json
{ "job_id": "uuid", "status": "pending"|"completed", "cache_hit": false }
```

### `GET /v1/jobs/{job_id}`

```json
{
  "job_id": "uuid",
  "status": "pending"|"processing"|"completed"|"failed",
  "cache_hit": false,
  "recipe": { /* RecipePublic */ } | null,
  "error": null
}
```

No `cost_cents`, no transcript.

### `GET /v1/me/recipes`

```json
{
  "items": [{
    "id": "uuid",
    "title": "…",
    "platform": "tiktok",
    "source_url": "https://…",
    "thumbnail_url": "https://…",
    "author": "…",
    "servings": 4,
    "prep_minutes": 10,
    "cook_minutes": 20,
    "saved_at": "2026-09-02T12:00:00Z"
  }]
}
```

### `GET /v1/recipes/{recipe_id}`

Full **RecipePublic** — only if user saved this recipe (else 403).

### `DELETE /v1/me/recipes/{recipe_id}`

`{ "ok": true }` — removes from user's list, not global cache.

### `DELETE /v1/me`

`{ "ok": true }` — deletes account server-side.

---

## 6. Data models (Swift)

Use `JSONDecoder` with `.convertFromSnakeCase`.

```swift
struct MeResponse: Decodable {
    let id: UUID
    let displayName: String?
    let isPro: Bool
    let proExpiresAt: Date?
    let freeUsedThisWeek: Int
    let freeLimit: Int
    let freeRemaining: Int
    let proRemainingCents: Double?
}

struct ExtractRequest: Encodable { let url: String }

struct ExtractJobResponse: Decodable {
    let jobId: UUID
    let status: String
    let cacheHit: Bool
}

struct JobResponse: Decodable {
    let jobId: UUID
    let status: String
    let cacheHit: Bool
    let recipe: RecipePublic?
    let error: String?
}

struct RecipeSummary: Decodable, Identifiable {
    let id: UUID
    let title: String
    let platform: String
    let sourceUrl: String
    let thumbnailUrl: String?
    let author: String?
    let servings: Int?
    let prepMinutes: Int?
    let cookMinutes: Int?
    let savedAt: Date
}

struct RecipeListResponse: Decodable {
    let items: [RecipeSummary]
}

struct RecipePublic: Decodable, Identifiable {
    let id: UUID
    let title: String
    let ingredients: [Ingredient]
    let steps: [Step]
    let servings: Int?
    let prepMinutes: Int?
    let cookMinutes: Int?
    let tags: [String]
    let sourceUrl: String
    let platform: String
    let thumbnailUrl: String?
    let author: String?
    let description: String?
}

struct Ingredient: Decodable {
    let name: String
    let quantity: String?
    let unit: String?
}

struct Step: Decodable {
    let order: Int
    let text: String
    let durationMinutes: Int?
}

struct QuotaErrorDetail: Decodable {
    let code: String
    let message: String
}
```

**Not in API responses:** `raw_transcript`, `confidence`, `missing_fields`, `cost_cents`, `email`.

`platform`: `tiktok` | `youtube` | `instagram` | `facebook` | `unknown`

---

## 7. Quotas & errors

| Plan | Rule |
|------|------|
| **Free** | 1 import / calendar week (UTC Mon–Sun). Cache hit or miss both count. |
| **Pro** | Unlimited; cache **miss** blocked when monthly OpenAI cost ≥ fair-use budget. Cache hits always free. |

Limits stored in Supabase (`app_settings` + per-user `profiles`). Superwall webhook sets `pro_monthly_price_cents` on subscribe.

### HTTP 403 — show paywall or message

**Free limit:**

```json
{
  "detail": {
    "code": "FREE_WEEKLY_LIMIT",
    "message": "Free plan: 1 recipe(s) per week. Upgrade to Pro.",
    "free_used_this_week": 1,
    "free_limit": 1
  }
}
```

→ Present Superwall paywall.

**Pro fair-use:**

```json
{
  "detail": {
    "code": "PRO_FAIR_USE_LIMIT",
    "message": "Pro fair-use limit reached this month (keeps margin).",
    "pro_cost_cents_this_month": 400,
    "pro_budget_cents": 399.2,
    "pro_monthly_price_cents": 499
  }
}
```

→ Soft message: try a link already imported, or wait until next month.

### Superwall iOS (required after login)

```swift
Superwall.configure(apiKey: "pk_3QyV6dXg2nPMj9gDTpZkF")
Superwall.shared.identify(userId: supabaseUserId.uuidString)
Superwall.shared.setUserAttributes(["supabase_user_id": supabaseUserId.uuidString])
```

Register paywall trigger e.g. on `FREE_WEEKLY_LIMIT` or "Upgrade" button.

---

## 8. Suggested `ReciAppAPI` service (Swift)

```swift
final class ReciAppAPI {
    let baseURL: URL
    var accessToken: String?

    func me() async throws -> MeResponse { … GET /v1/me … }
    func extract(url: URL) async throws -> ExtractJobResponse { … POST /v1/extract … }
    func job(id: UUID) async throws -> JobResponse { … GET /v1/jobs/{id} … }

    func extractAndWait(url: URL, pollInterval: Duration = .seconds(2)) async throws -> RecipePublic {
        let started = try await extract(url: url)
        if started.status == "completed", started.cacheHit {
            let j = try await job(id: started.jobId)
            guard let r = j.recipe else { throw APIError.noRecipe }
            return r
        }
        while true {
            let j = try await job(id: started.jobId)
            switch j.status {
            case "completed":
                guard let r = j.recipe else { throw APIError.noRecipe }
                return r
            case "failed":
                throw APIError.extractFailed(j.error ?? "unknown")
            default:
                try await Task.sleep(for: pollInterval)
            }
        }
    }

    func myRecipes() async throws -> [RecipeSummary] { … GET /v1/me/recipes … }
    func recipe(id: UUID) async throws -> RecipePublic { … GET /v1/recipes/{id} … }
    func deleteRecipe(id: UUID) async throws { … DELETE /v1/me/recipes/{id} … }
    func deleteAccount() async throws { … DELETE /v1/me … }
}
```

---

## 9. Cache behavior

Same normalized URL → instant `completed` + `cache_hit: true`, no OpenAI cost. Still counts toward Free weekly limit.

---

## 10. Supabase Apple Sign In setup

1. Apple Developer → App ID → enable **Sign In with Apple**.
2. Xcode → Signing & Capabilities → **Sign In with Apple**.
3. Supabase → Authentication → Providers → Apple:
   - Enable
   - **Client IDs:** your iOS bundle id (e.g. `com.yourco.ReciApp`)
   - **Secret Key:** leave empty for native iOS
   - **Allow users without an email:** ON

---

## 11. Checklist before TestFlight

- [ ] API base URL + Supabase anon in app
- [ ] Apple Sign In works → JWT
- [ ] Superwall identify + attributes after login
- [ ] Import flow: paste TikTok/YouTube URL → recipe UI
- [ ] Home list loads summaries
- [ ] Detail shows ingredients + steps
- [ ] Free limit → paywall
- [ ] Share Extension passes URL to main app
- [ ] Delete account works

---

## 12. Admin (NOT in App Store build)

Dashboard: `https://reciapp-4ih5.onrender.com/dashboard` (password in Render env).

Admin API uses `X-API-Key` — never embed in iOS.

---

## 13. Supported URL examples

```
https://vm.tiktok.com/ZGdQJr1J4/
https://www.tiktok.com/@user/video/123
https://www.youtube.com/watch?v=…
https://youtu.be/…
https://www.instagram.com/reel/…
https://www.facebook.com/…/videos/…
```

Server normalizes URLs before cache lookup.
