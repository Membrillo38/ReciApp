# Reliable Extraction, Carousels, and Superwall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize ReciApp import and refresh flows, add end-to-end TikTok carousel support, and complete Superwall purchase lifecycle with simulator and live read-only verification.

**Architecture:** Keep one canonical recipe cache row per normalized source URL. Make extraction and translation jobs idempotent, recoverable, and language-aware at their API boundary. Persist a bounded list of carousel image URLs with the recipe, render it through a native SwiftUI paging view, and keep subscription identity in one `SubscriptionService` owned by the authenticated app session.

**Tech Stack:** FastAPI, Pydantic, Supabase/Postgres, OpenAI structured output, yt-dlp, SwiftUI iOS 17, Supabase Swift, SuperwallKit, `xcodebuild`, `xcrun simctl`.

**Spec:** `docs/superpowers/specs/2026-09-07-reliable-extraction-carousel-superwall.md`

## Global Constraints

- Preserve current uncommitted changes and worktree data; do not reset, checkout, clean, or delete user files.
- Keep one base recipe per `source_url_norm`; keep translations keyed by `(recipe_id, language_code)`.
- Keep iOS deployment target `17.0` and bundle identifier `com.membri.reciapp`.
- Never log credentials, raw transcripts, recipe text, or full server payloads.
- No remote Supabase DDL in this rollout; verify existing migrations read-only.
- No Liquid Glass, card/page borders, or strokes in the iOS UI.

---

### Task 1: Capture baseline and make job ownership/idempotency explicit

**Files:**
- Modify: `app/main.py`
- Modify: `app/store.py`
- Modify: `app/job_guard.py`
- Modify: `app/pipeline.py`
- Modify: `tests/test_job_reliability.py`
- Modify: `IOS_INTEGRATION.md`

**Interfaces:**
- `create_job(...) -> dict` remains the job creation boundary.
- `get_active_job(source_url_norm, language_code, job_kind, recipe_id) -> dict | None` returns only a compatible active job.
- `user_can_access_job(job_id, user_id) -> bool` distinguishes missing ownership from database failure.
- Test-only helpers in `tests/test_job_reliability.py`: `extract_job_language_matches`, `upsert_recipe_after_unique_conflict`, `resolve_job_access`, and `JobAccessUnavailable` model the three regression seams without adding production API surface.

- [ ] **Step 1: Add failing tests for the observed races.**

```python
def test_active_extract_job_does_not_claim_incompatible_language():
    row = {"job_kind": "extract", "language_code": "es-ES"}
    assert extract_job_language_matches(row, "en-US") is False


def test_duplicate_recipe_insert_returns_existing_row(monkeypatch):
    # The store must retry the read after a unique conflict instead of exposing 500.
    assert upsert_recipe_after_unique_conflict("https://www.tiktok.com/Z1") == "existing"


def test_access_lookup_does_not_turn_storage_error_into_not_your_job():
    with pytest.raises(JobAccessUnavailable):
        resolve_job_access(storage_error=True)
```

Run: `./.venv/bin/python -m pytest tests/test_job_reliability.py -q` when pytest is available; otherwise run the repository's test functions with the bundled Python fallback runner.

Expected: FAIL because helpers and the unique-conflict recovery contract do not exist.

- [ ] **Step 2: Make active-job joins compatible and fail closed.**

Keep extraction jobs globally deduplicated by normalized source URL, but do not return an active job as if it already represented a different requested language. When a base extraction is active, the API must preserve the base job access and resolve the requested translation after the base row exists. Make `grant_job_access` surface a typed storage failure; make `user_can_access_job` surface the same failure instead of returning a false 403. Return `503` with a stable detail code for unavailable job access.

- [ ] **Step 3: Recover unique recipe races.**

In `upsert_recipe`, catch only the Supabase unique violation for `source_url_norm`, re-read `get_recipe_by_norm`, and return the existing row. Re-raise unrelated database errors. Ensure the winning recipe ID is used for `save_user_recipe`, job completion, and usage settlement.

- [ ] **Step 4: Make job completion and stale-job behavior deterministic.**

Add `created_at`/`updated_at` age checks in `get_job_status`. If a pending or processing job exceeds `settings.job_ttl_seconds`, update it to `failed` with a stable retryable error and settle any reservation as failed. Never leave a user polling forever after a worker restart. Keep `progress` monotonic and set `100` on completion.

- [ ] **Step 5: Add request-flow regression tests.**

Cover cache hit, concurrent cache miss, different-language request during an active base job, non-owner access, storage outage, and stale job. Mock Supabase at the store boundary; assert no duplicate recipe insert and no duplicate `user_recipes` link.

- [ ] **Step 6: Run backend verification.**

Run: `PYTHONPYCACHEPREFIX=/tmp/reciapp-pycache ./.venv/bin/python -m compileall -q app tests`, the focused test runner, and `git diff --check`.

Expected: all tests pass; only typed errors reach API responses; no credentials appear in logs or tests.

---

### Task 2: Harden media extraction and structured recipe generation

**Files:**
- Modify: `app/extract.py`
- Modify: `app/tiktok_slides.py`
- Modify: `app/transcript.py`
- Modify: `app/recipe_builder.py`
- Modify: `app/pipeline.py`
- Modify: `tests/test_extraction_fallbacks.py`

**Interfaces:**
- `fetch_media_info(url: str) -> MediaInfo` keeps its public shape.
- `fetch_tiktok_slides(url: str) -> SlideInfo | None` returns bounded, ordered slide URLs.
- `build_recipe(...) -> Recipe` validates all model output before returning.
- Test-only fixture helpers in `tests/test_extraction_fallbacks.py`: `fetch_media_info_from_fixture`, `run_fixture_pipeline`, and `request_structured_recipe_with_responses` isolate network/model inputs.

- [ ] **Step 1: Add deterministic fixture tests for fallbacks and malformed output.**

```python
def test_subtitle_precedes_audio(monkeypatch):
    info = fetch_media_info_from_fixture("subtitle-fixture")
    assert info.subtitles_text == "recipe text"
    assert info.audio_path is None


def test_empty_transcription_falls_back_to_description(monkeypatch):
    recipe = run_fixture_pipeline(description="Mix flour and eggs", transcript="")
    assert recipe.title
    assert recipe.missing_fields


def test_structured_output_retries_invalid_json(monkeypatch):
    result = request_structured_recipe_with_responses(['{"title":"cut', '{"title":"ok"}'])
    assert result["title"] == "ok"
```

Expected before implementation: FAIL on empty-transcript fallback and invalid JSON recovery.

- [ ] **Step 2: Bound and classify media fallback failures.**

Keep subtitle-first behavior. If audio download or transcription returns no text, use non-empty title/description/slide text when available. Raise an error only when every source is empty, with a stable message such as `No usable recipe text found in source`. Include platform, stage, duration, and attempt in logs; never include transcript or keys.

- [ ] **Step 3: Make TikTok carousel parsing robust.**

Accept both TikTok hydration structures already supported plus nested `imagePost.images` variants. Preserve URL order, discard duplicates/empty values, cap total slides to a configured safe maximum, and use the highest usable URL from each `urlList`. Return `None` only when no image post exists.

- [ ] **Step 4: Retry model output with bounded policy.**

If the response is refused, empty, malformed JSON, or truncated, retry once with a shorter source prompt and the larger existing token budget. Parse JSON only after confirming content exists. Validate `ingredient_sections`, `tips`, `steps`, and scalar fields through Pydantic. Convert recoverable empty arrays to localized fallback values; reject invented or structurally invalid data with a stable `ExtractError`.

- [ ] **Step 5: Add pipeline stage progress and bounded OCR.**

Set progress for media discovery, slide OCR, transcription, recipe generation, persistence, and completion. OCR every bounded usable carousel slide, continue when one slide image is unavailable, and fail only when all OCR inputs fail. Keep OpenAI call and cost accounting aligned with actual stages.

- [ ] **Step 6: Run fixture tests and compile.**

Run focused extraction tests, all backend test functions, compileall with `PYTHONPYCACHEPREFIX=/tmp/reciapp-pycache`, and `git diff --check`.

---

### Task 3: Persist and expose carousel images

**Files:**
- Create: `supabase/migrations/010_recipe_carousel_images.sql`
- Modify: `app/models.py`
- Modify: `app/tiktok_slides.py`
- Modify: `app/store.py`
- Modify: `app/pipeline.py`
- Modify: `app/main.py`
- Modify: `IosAPP/ReciApp/Models/Models.swift`
- Modify: `IosAPP/ReciApp/Services/APIClient.swift`
- Modify: `tests/test_carousel_contract.py`

**Interfaces:**
- `Recipe.carousel_image_urls: list[str]` and `RecipePublic.carousel_image_urls: list[str]` are bounded, ordered, duplicate-free.
- `RecipeSummary` remains small and uses only `thumbnail_url`; detail/job payloads carry carousel URLs.
- `GET /v1/recipes/{id}` and completed `GET /v1/jobs/{id}` expose `carousel_image_urls`.
- Test-only contract fixtures in `tests/test_carousel_contract.py` construct rows with duplicate/empty URLs and verify canonicalization.

- [ ] **Step 1: Add contract tests before schema/code.**

```python
def test_carousel_urls_are_ordered_and_bounded():
    recipe = recipe_public_from_row({"id": str(uuid4()), "title": "x", "carousel_image_urls": ["a", "a", "", "b"]})
    assert recipe.carousel_image_urls == ["a", "b"]


def test_ios_recipe_model_decodes_carousel_urls_with_empty_legacy_default():
    source = Path("IosAPP/ReciApp/Models/Models.swift").read_text()
    assert "carouselImageUrls" in source
```

Expected: FAIL because database/model/client field does not exist.

- [ ] **Step 2: Create additive migration file.**

Use `supabase migration new recipe_carousel_images` if the CLI is available; otherwise write the exact reviewed migration file only after confirming no live DDL is being applied. Add `carousel_image_urls jsonb not null default '[]'::jsonb` to `public.recipes`, keep RLS unchanged, and add a JSON-array length check only if compatible with existing rows. Do not run `supabase db push` in this task.

- [ ] **Step 3: Store carousel URLs safely.**

Normalize URLs only for validation, preserve display order, remove duplicates, cap length and per-URL size, and set the first usable URL as `thumbnail_url` for old clients. Keep URLs in the recipe row so global cache and translations retain stable media metadata.

- [ ] **Step 4: Extend Python and Swift contracts.**

Add defaults so legacy rows decode. Ensure `recipe_public_from_row`, `recipe_from_row`, `recipe_to_row`, `JobResponse`, and Swift `RecipePublic` all preserve the field without making old server rows fail. Keep `RecipeSummary` unchanged except optional compatibility decoding if required.

- [ ] **Step 5: Run contract tests and schema lint.**

Run focused tests, SQL text checks for additive column/default/RLS safety, compileall, and `git diff --check`. Verify remote schema read-only; do not apply migration.

---

### Task 4: Render carousel UI and stabilize iOS request lifecycle

**Files:**
- Create: `IosAPP/ReciApp/Views/RecipeCarouselView.swift`
- Modify: `IosAPP/ReciApp/Views/RecipeDetailView.swift`
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`
- Modify: `IosAPP/ReciApp/Services/APIClient.swift`
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`
- Modify: `IosAPP/ReciApp/Views/ImportView.swift`
- Modify: `tests/test_ios_contract.py`

**Interfaces:**
- `RecipeCarouselView(images: [URL], height: CGFloat) -> some View` renders one image or a native paging carousel with stable accessibility labels.
- `APIClient.job(id:language:token:)` sends the selected language on polling.
- `AppViewModel.fetchRecipe(_:)` and `refreshAll()` preserve visible state on transient failure.

- [ ] **Step 1: Add Swift contract tests/source assertions.**

```python
def test_carousel_uses_native_paging_and_no_liquid_glass():
    source = Path("IosAPP/ReciApp/Views/RecipeCarouselView.swift").read_text()
    assert "TabView" in source
    assert "PageTabViewStyle" in source
    assert "Material" not in source
```

- [ ] **Step 2: Implement minimal solid carousel.**

Use `TabView(selection:)` with `.page(indexDisplayMode: .automatic)`, `AsyncImage`, a local fallback tint, stable slide count labels, and no border/stroke/material. Keep a single image visually identical to current hero. Hide pagination only when one image exists.

- [ ] **Step 3: Integrate carousel into detail hero.**

Build image URLs from `carouselImageUrls` plus `thumbnailUrl` fallback, remove duplicates, preserve order, and render `RecipeCarouselView` in the current 360-point hero. Keep platform/title fallback when all images fail. Do not change unrelated folder controls.

- [ ] **Step 4: Make all requests language-aware and retry-safe.**

Pass `AppLanguageStore.current.serverCode` to job polling and recipe detail. Retry 401 once after `AuthService.refreshSession()`. Retry transient 408/429/5xx/network failures with capped backoff. Do not clear `recipes`, `me`, or the last successful detail before a refresh succeeds. Do not call `refreshAll()` repeatedly after every Superwall callback without a bounded delay.

- [ ] **Step 5: Handle completed jobs without missing recipe payload.**

When a completed response has no inline recipe, fetch the recipe detail by ID with language. When a translation is pending, retain the base recipe if present and replace it when localized payload arrives. Surface a retry action with a correlation-safe message.

- [ ] **Step 6: Build, run, and visually verify.**

Use the available booted simulator after CoreSimulatorService recovers. Build `ReciApp` and `ReciAppShare` with `CODE_SIGNING_ALLOWED=NO`, launch, capture UI description and screenshot, verify folder-first home, detail hero, one-image fallback, multi-image carousel, accessibility labels, and no `stroke`/`border`/Liquid Glass source regressions.

---

### Task 5: Complete Superwall subscription lifecycle

**Files:**
- Modify: `IosAPP/ReciApp/Services/SubscriptionService.swift`
- Modify: `IosAPP/ReciApp/ReciAppApp.swift`
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`
- Modify: `IosAPP/ReciApp/Views/ProfileView.swift`
- Modify: `IosAPP/ReciApp/Services/AuthService.swift`
- Modify: `app/superwall.py`
- Modify: `app/main.py`
- Modify: `tests/test_superwall_contract.py`
- Modify: `IOS_INTEGRATION.md`

**Interfaces:**
- `SubscriptionService.configure()` is idempotent.
- `identify(userID:)`, `reset()`, `presentUpgrade(onFinished:)`, and `restorePurchases(onFinished:)` remain main-actor isolated.
- Backend webhook stays `POST /v1/webhooks/superwall` and remains Svix-verified/idempotent.

- [ ] **Step 1: Add contract tests.**

```python
def test_subscription_lifecycle_contains_identify_attributes_restore_and_placement():
    source = Path("IosAPP/ReciApp/Services/SubscriptionService.swift").read_text()
    assert "identify(userId:" in source
    assert "setUserAttributes" in source
    assert "restore" in source.lower()
    assert "free_limit_reached" in source


def test_webhook_rejects_wrong_application_and_replays_idempotently():
    assert apply_superwall_event({"applicationId": 54783, "id": "evt-1"})["status"] in {"processed", "skipped"}
```

- [ ] **Step 2: Make identity lifecycle explicit.**

After session restore and Apple sign-in, call `identify` and set `supabase_user_id`. On sign-out, reset Superwall before clearing local session. Do not identify preview/debug users or anonymous sessions.

- [ ] **Step 3: Wire purchase, restore, and server refresh.**

Keep quota denial placement `free_limit_reached`. Add a restore action in ProfileView calling Superwall restore; after purchase or restore callback, refresh `/v1/me` with bounded retries so the webhook has time to update `is_pro`. Keep UI responsive if webhook is delayed and report current plan accurately.

- [ ] **Step 4: Audit backend webhook identity and event ordering.**

Verify event IDs are unique, old events cannot overwrite newer subscription state, wrong application IDs are skipped, price/proceeds fields remain server-side, and no user payload is emitted to logs. Add tests for purchase, renewal, expiration, duplicate, unknown-user, and wrong-application events.

- [ ] **Step 5: Run sandbox-safe verification.**

Build without requiring StoreKit purchase credentials. Use simulator UI to verify configuration, profile restore action, quota paywall presentation path, sign-out reset, and refresh after callback. Real Apple billing/webhook confirmation requires configured Superwall/Apple sandbox products and cannot be proven by build output alone.

---

### Task 6: End-to-end evidence and stop gate

**Files:**
- Modify: `scripts/e2e_extract.sh`
- Create: `scripts/e2e_matrix.sh`
- Modify: `README.md`
- Modify: `IOS_INTEGRATION.md`
- Modify: `docs/SECURITY_RUNBOOK.md`

**Interfaces:**
- `scripts/e2e_extract.sh` accepts `API`, `API_KEY`, Supabase credentials, source URL, and language without printing secrets.
- `scripts/e2e_matrix.sh` executes bounded repeated cache, language, carousel, and failure-retry cases.

- [ ] **Step 1: Add matrix cases for supplied sources.**

Run each supplied TikTok URL through URL normalization, one warm cache request, one second request, one Spanish request, and job polling. Record only status, cache hit, job ID, progress, recipe ID, language, carousel count, and elapsed time. Never print tokens or recipe transcripts.

- [ ] **Step 2: Verify live server and database read-only.**

Check `/health`, latest Render deploy/logs/metrics after workspace confirmation, Supabase `list_migrations`, tables, job counts, and request latency. Do not alter Render env vars or apply Supabase DDL automatically.

- [ ] **Step 3: Run iOS simulator matrix.**

For at least one current iPhone simulator: clean build, launch, refresh empty/warm home, open cached detail, import a supplied TikTok source, poll to completion/failure, relaunch during polling, switch locale, render carousel, sign out/in, and inspect accessibility/screenshot. Repeat import three times to distinguish deterministic failures from transient ones.

- [ ] **Step 4: Run final gates.**

Run focused and full backend tests, compileall with writable pycache, `git diff --check`, clean iOS build, source audit for `stroke`/`border`/Liquid Glass, and summarize any environment blocker separately from product failures.

- [ ] **Step 5: Stop only when evidence is complete.**

Report fixed causes, exact tests, supplied URL results, simulator evidence, remaining external prerequisites, and files changed. Mark goal complete only when required implementation and verifications pass; leave goal active if live Render or CoreSimulator access remains blocked.
