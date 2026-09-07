# Background Recipe Translation Spec

## Goal

Return each recipe in the requesting user's language, share translations globally between users, avoid duplicate translations, and keep translation work asynchronous.

## Product decision

Use six canonical Latin-script locales only:

- `en-US` — English
- `es-ES` — Spanish
- `fr-FR` — French
- `de` — German
- `it` — Italian
- `pt-BR` — Portuguese

Regional duplicates collapse into one canonical locale. Non-Latin scripts are removed from the in-app picker and shipped resources. `en-US` remains fallback.

## Architecture

1. `recipes` stores one extracted base recipe per normalized source URL. The row records the language used when the base recipe was generated.
2. `recipe_translations` stores only generated translations, globally, keyed by `(recipe_id, language_code)`. No `user_id` appears in this cache. One translation serves every user.
3. A request first checks the base recipe, then the global translation cache. Cache hit returns immediately with no AI call and zero translation cost.
4. Cache miss creates one deduplicated background translation job for `(recipe_id, language_code)`. The requesting user receives job progress and the completed localized recipe.
5. Concurrent users requesting the same missing translation join the same active job. Different target languages run independently.
6. No proactive translation of all six languages. Translation happens only when requested; this is the only design satisfying minimum cost, minimum database growth, and no unnecessary work. Background warming may be added later under a budget, but cannot be free.

## Hard limits

“Translate all six languages for every recipe”, “zero AI cost”, and “zero database growth” cannot all be true. This design pays at most once per recipe-language pair, stores at most one shared translation per pair, and never makes a user wait for synchronous translation work.

## Data contract

- `recipes.source_url_norm` remains unique.
- `recipes.language_code` records base/generated language and defaults to `en-US`.
- `recipe_translations.recipe_id` references `recipes.id`.
- `recipe_translations.language_code` is allowlisted and unique per recipe.
- `recipe_translations.payload` contains only translated user-facing structured fields.
- `extract_jobs.job_kind` is `extract` or `translation`.
- Active extract uniqueness uses `source_url_norm`.
- Active translation uniqueness uses `(recipe_id, language_code)`.
- Translation cache and jobs are server-owned; users can access only recipes they saved and jobs granted to them.

## Acceptance criteria

- Picker offers `System default` plus exactly six canonical locales.
- User A imports URL in Spanish: one extraction, Spanish base row.
- User B imports same URL in Spanish: immediate cache hit; no extraction or translation call.
- User B imports same URL in English: one background translation; later users in English hit shared cache.
- Repeated English requests never create another translation row or AI call.
- Database has one base recipe plus at most one translation payload per supported target language, never one copy per user.
- Import endpoint remains asynchronous; translation errors do not corrupt base recipe or other language caches.
- Existing saved recipes remain readable after locale reduction.
- Focused Python tests, clean iOS build, and API/cache proof pass.
