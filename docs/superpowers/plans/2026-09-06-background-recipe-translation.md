# Background Recipe Translation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce ReciApp to six canonical Latin-script locales and add a globally shared, language-keyed background translation cache.

**Architecture:** Keep one base recipe per normalized source URL and store generated translations in a shared `recipe_translations` table keyed by recipe and language. Requests hit the base row or translation row before creating any AI work; one active translation job is shared by all concurrent users for the same pair.

**Tech Stack:** FastAPI, Pydantic, Supabase/Postgres migrations, SwiftUI, Swift Concurrency, OpenAI structured output, background FastAPI jobs.

**Spec:** `docs/superpowers/specs/2026-09-06-background-recipe-translation.md`

## Global Constraints

- Supported in-app locales: exactly `en-US`, `es-ES`, `fr-FR`, `de`, `it`, `pt-BR`, plus `System default`.
- One base `recipes` row per `source_url_norm`; one shared translation payload per `(recipe_id, language_code)` at most.
- Never include `user_id` in translation-cache uniqueness or payload ownership.
- Preserve auth, quota, spend ledger, source URL validation, and user ownership behavior.
- No recipe text, credentials, or raw server payloads in logs.
- Do not apply live Supabase DDL without explicit user authorization.

---

### Task 1: Canonical six-language registry and catalog

**Files:**
- Modify: `app/localization.py`
- Modify: `IosAPP/ReciApp/Services/Localization.swift`
- Modify: `IosAPP/ReciApp/Localizable.xcstrings`
- Modify: `tests/test_localization.py`
- Modify: `docs/superpowers/plans/2026-09-06-localization.md`

**Interfaces:**
- `SUPPORTED_LANGUAGE_CODES` becomes `{en-US, es-ES, fr-FR, de, it, pt-BR}`.
- `AppLanguage.supportedLanguages` exposes the same six locales.
- Legacy region values normalize to their canonical locale.

- [x] **Step 1: Write six-locale assertions**

```python
def test_allowlist_has_six_canonical_latin_locales():
    expected = {"en-US", "es-ES", "fr-FR", "de", "it", "pt-BR"}
    assert set(SUPPORTED_LANGUAGE_CODES) == expected
    assert len(SUPPORTED_LANGUAGE_CODES) == 6
```

- [x] **Step 2: Run tests and verify the old registry is rejected**

Run the focused runner from `tests/test_localization.py`.

Expected before the implementation: FAIL because the old registry contained more than the six canonical locales.

- [x] **Step 3: Prune registries and String Catalog**

Keep six canonical locale entries. Map `en`, `en-GB`, `en-CA`, `en-AU` to `en-US`; `es-MX` to `es-ES`; `fr-CA` to `fr-FR`; `pt-PT` to `pt-BR`. Remove unused locale entries from the catalog.

- [x] **Step 4: Run catalog validation and tests**

Verify every catalog key has exactly six supported locale values, placeholders match, and no removed locale remains.

- [ ] **Step 5: Commit**

```bash
git add app/localization.py IosAPP/ReciApp/Services/Localization.swift IosAPP/ReciApp/Localizable.xcstrings tests/test_localization.py docs/superpowers/plans/2026-09-06-localization.md
git commit -m "feat: reduce app locales to six"
```

### Task 2: Shared translation cache schema

**Files:**
- Create: `supabase/migrations/008_recipe_translations.sql`
- Modify: `app/models.py`
- Create: `app/translation_cache.py`
- Create: `tests/test_translation_cache.py`

**Interfaces:**
- `get_recipe_translation(recipe_id: UUID, language_code: str) -> dict | None`
- `upsert_recipe_translation(recipe_id: UUID, language_code: str, payload: dict) -> dict`
- `get_active_translation_job(recipe_id: UUID, language_code: str) -> dict | None`

- [ ] **Step 1: Add failing schema and cache contract tests**

Assert migration creates `recipe_translations`, unique `(recipe_id, language_code)`, no `user_id`, and allowlisted language validation.

- [ ] **Step 2: Create idempotent migration**

Add `job_kind` to `extract_jobs`; create `recipe_translations` with structured JSON payload, content fingerprint, timestamps, RLS enabled, service-role-only writes, and a unique `(recipe_id, language_code)` index. Add active translation-job uniqueness on `(recipe_id, language_code)`.

- [ ] **Step 3: Implement cache access layer**

Normalize target language before reads/writes, reject unsupported codes, and never log payload contents.

- [ ] **Step 4: Run focused tests and diff check**

Expected: PASS.

### Task 3: Background translation pipeline and API flow

**Files:**
- Modify: `app/main.py`
- Modify: `app/store.py`
- Modify: `app/pipeline.py`
- Modify: `app/recipe_builder.py`
- Modify: `app/models.py`
- Modify: `tests/test_translation_cache.py`

**Interfaces:**
- `run_translation_job(job_id: UUID, user_id: UUID, recipe_id: UUID, language_code: str) -> None`
- `get_recipe_for_language(recipe_row: dict, language_code: str) -> dict`
- `create_job(..., job_kind: str = "extract")`

- [ ] **Step 1: Add failing request-flow tests**

Cover base-language hit, translated-language hit, missing translation, concurrent same-pair join, and different-language independence.

- [ ] **Step 2: Separate extraction and translation jobs**

Keep extraction cache keyed by URL. On URL hit, resolve base row first; return base immediately when language matches; otherwise check translation cache.

- [ ] **Step 3: Enqueue or join translation job**

Create one active translation job per recipe and target language, grant access to joining users, and return pending status without calling translation synchronously in the request handler.

- [ ] **Step 4: Implement structured translation worker**

Translate title, description, section titles, ingredient names/units, steps, tips, tags, and missing fields. Preserve quantities, durations, IDs, URL, platform, author, thumbnail, confidence, and source metadata. Validate output with existing Pydantic models before storing.

- [ ] **Step 5: Return localized payload from job polling**

Resolve translation payload for translation jobs; never expose another user's job or recipe. Cache errors remain isolated to target language.

- [ ] **Step 6: Run tests, compile, and diff check**

Run focused tests, compileall, and `git diff --check`.

### Task 4: iOS language propagation and localized recipe retrieval

**Files:**
- Modify: `IosAPP/ReciApp/Models/Models.swift`
- Modify: `IosAPP/ReciApp/Services/APIClient.swift`
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`
- Modify: `IosAPP/ReciApp/Views/RecipeDetailView.swift`
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`

**Interfaces:**
- `RecipePublic.languageCode: String`
- `RecipeSummary.languageCode: String`
- API requests include canonical `language` on extraction and recipe fetch.

- [ ] **Step 1: Add failing decoding/request tests**

Verify language code decodes and selected language is sent on extraction and detail fetch.

- [ ] **Step 2: Pass selected language through all recipe reads**

Use `AppLanguageStore.current.serverCode` for extract, job polling, summary refresh, and detail fetch. Keep IDs stable so one saved recipe can display different cached translations.

- [ ] **Step 3: Handle pending translation without blocking navigation**

Show existing/base recipe while translation job runs, then replace content when the localized payload arrives. Do not duplicate `user_recipes` links.

- [ ] **Step 4: Build and runtime-test English/Spanish shared-cache flow**

Verify same recipe ID remains stable while response language changes.

### Task 5: End-to-end gates and deployment boundary

**Files:**
- Modify: `IOS_INTEGRATION.md`
- Modify: `IosAPP/README.md`
- Modify: `docs/superpowers/specs/2026-09-06-background-recipe-translation.md`
- Modify: `docs/superpowers/plans/2026-09-06-background-recipe-translation.md`

- [ ] **Step 1: Run backend tests, compile, and schema lint**

Verify migration SQL, allowlist, payload validation, and job deduplication.

- [ ] **Step 2: Run clean iOS build**

Use existing iPad Simulator destination and a fresh derived-data path with code signing disabled.

- [ ] **Step 3: Verify runtime behavior**

Test System default plus six locales, same URL by two users, cache hit in same language, one background translation for a new language, and stable recipe ownership.

- [ ] **Step 4: Verify live Supabase read-only**

Confirm migration history and columns/indexes. Applying migrations remains a separate explicitly authorized operation.

- [ ] **Step 5: Record limits and stop**

Document that one AI translation per recipe-language pair is the lower bound for server-side translation. Do not add proactive six-language generation or per-user copies.
