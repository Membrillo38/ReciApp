# Reliable Extraction, Carousels, and Superwall Spec

**Date:** 2026-09-07
**Project:** ReciApp

## Goal

Make recipe import deterministic across TikTok video posts, TikTok photo carousels, YouTube, Instagram, and Facebook; keep saved recipes visible when a refresh or detail request is transient; expose carousel images in recipe detail; then finish Superwall identity, paywall, restore, and subscription refresh integration.

## Evidence baseline

- Supabase project `nzimdcjxgklopythnpfi` is `ACTIVE_HEALTHY`.
- Migrations `001` through `009` are present in the remote database.
- Remote jobs currently show 8 completed and 7 failed extract jobs.
- Observed failures include `Transcription returned empty text`, malformed structured JSON, and an old duplicate `source_url_norm` race.
- `/v1/me` has 220 successful requests averaging approximately 660 ms; `/v1/me/recipes` has 203 successful requests averaging approximately 220 ms.
- TikTok slide extraction exists in `app/tiktok_slides.py`, but recipe persistence and iOS models currently retain only one `thumbnail_url`.
- Superwall SDK and backend webhook code exist, but purchase presentation, restoration, identity lifecycle, and post-purchase server refresh need end-to-end proof.

## Functional requirements

1. Every accepted source URL normalizes to one stable cache key.
2. Concurrent imports of the same source never fail because two workers insert the same recipe.
3. A job always reaches `completed` or a user-readable `failed` state; stale jobs cannot spin forever.
4. Missing subtitles/audio do not produce a false success or an opaque empty-transcript error. Fallback order and failure reason remain observable without secrets or recipe text.
5. Structured recipe output is retried when the model truncates or returns invalid JSON, and validated before persistence.
6. TikTok photo posts preserve all usable slide image URLs, OCR all supported slides within a bounded cost, and display them as an interactive carousel in iOS detail.
7. Base recipe and translation language remain independent under concurrent requests.
8. iOS refresh/detail/import retries do not clear already-visible recipes, do not duplicate user links, and refresh an expired Supabase session once before retrying.
9. Superwall identifies the Supabase user after session restore/sign-in, presents the configured placement on quota denial, supports restore purchases, and refreshes `/v1/me` after purchase/restore.
10. Verification includes backend tests, live read-only health/database checks, clean iOS build, simulator screenshots/accessibility, repeated import polling, cache-hit detail, carousel rendering, logout/login, and Superwall sandbox-safe flows.

## Constraints

- Keep iOS deployment target `17.0` and bundle identifier `com.membri.reciapp`.
- Keep supported locales exactly `en-US`, `es-ES`, `fr-FR`, `de`, `it`, and `pt-BR`, plus System default.
- Keep Supabase as recipe truth and local UserDefaults only for organization metadata and pending share handoff.
- Never ship `service_role`, Render `API_KEY`, OpenAI keys, dashboard credentials, or webhook secrets in iOS.
- Do not apply remote Supabase DDL in this task; migrations already exist remotely and schema changes require a separate explicit authorization.
- Preserve current uncommitted user changes and minimal solid UI style: no Liquid Glass, no card/page borders or strokes.
