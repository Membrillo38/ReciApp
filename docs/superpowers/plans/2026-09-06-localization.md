# ReciApp Localization and AI Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ReciApp device-language-aware with a six-language Settings override and globally cached language-specific server-generated recipes.

**Architecture:** Add one shared iOS language registry and local persistence, inject its selected `Locale` at the app root, and keep localized copy in SwiftUI's standard localization path. Extend the extract request with a normalized language code; propagate it through extraction and shared translation jobs. Keep one base recipe per source URL and one global translation payload per recipe-language pair.

**Tech Stack:** SwiftUI iOS 17, `@AppStorage`, `Locale`, Xcode String Catalog, FastAPI/Pydantic, OpenAI structured output, Supabase Postgres migration.

**Spec:** `docs/superpowers/specs/2026-09-06-localization.md`

## Global Constraints

- Keep existing folder-first single-page UI and minimal solid surfaces.
- Do not introduce Liquid Glass, card borders, or unrelated navigation changes.
- Preserve existing uncommitted worktree changes.
- Store language override locally; remote recipe rows remain authoritative.
- Server accepts only six canonical Latin-script identifiers and falls back safely to `en-US`.
- Never log tokens, API keys, raw prompts, or recipe transcripts.

---

### Task 1: Shared language registry and root locale

**Files:**
- Create: `IosAPP/ReciApp/Services/Localization.swift`
- Modify: `IosAPP/ReciApp/ReciAppApp.swift`
- Modify: `IosAPP/ReciApp.xcodeproj/project.pbxproj`
- Test: `IosAPP/ReciAppTests/LocalizationTests.swift` if test target exists; otherwise source-level checks.

**Interfaces:**
- Produces `AppLanguage.allCases`, `AppLanguage.system`, `AppLanguage.localeIdentifier`, `AppLanguage.serverCode`, and `AppLanguageStore`.
- Root reads `AppLanguageStore.current` and applies `.environment(\.locale, ...)`.

- [x] **Step 1: Add the six-code enum and local store.**

  Use six canonical identifiers, plus `system` as the non-App-Store override. Persist only the raw identifier under a versioned `UserDefaults` key. Resolve unsupported device languages to English (U.S.) for server requests.

- [x] **Step 2: Wire the source file into the app target.**

  Add the file reference and Sources build entry in the existing project file; do not touch package dependencies or unrelated target settings.

- [x] **Step 3: Inject locale at `RootView`.**

  Apply the selected locale above the existing view branches so login, onboarding, settings, home, detail, sheets, alerts, and accessibility copy all receive the same locale.

- [x] **Step 4: Verify registry behavior.**

  Run a small Swift compile/build check and assert there are exactly six non-system languages, unique raw values, and English fallback for an unsupported device locale.

### Task 2: Settings language selector and localized model copy

**Files:**
- Modify: `IosAPP/ReciApp/Views/ProfileView.swift`
- Modify: `IosAPP/ReciApp/Models/UserPreferences.swift`
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`
- Modify: `IosAPP/ReciApp/Views/OnboardingView.swift`
- Modify: `IosAPP/ReciApp/Views/LoginView.swift`
- Modify: `IosAPP/ReciApp/Views/ImportView.swift`
- Modify: `IosAPP/ReciApp/Views/RecipeDetailView.swift`
- Modify: `IosAPP/ReciApp/Models/Models.swift`
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`

**Interfaces:**
- Settings owns `@AppStorage(AppLanguageStore.storageKey)` and renders a `Picker` over `AppLanguage.allCases`.
- Model display strings use localization keys rather than hard-coded English `String` values.

- [x] **Step 1: Add language row to Settings.**

  Place it in the existing preferences card, show `System default` or the selected language name, preserve haptics, and make the picker accessible.

- [x] **Step 2: Convert model-generated copy.**

  Localize temperature/measurement names, folder sort names, status/error messages, plural recipe counts, and all visible static labels. Keep recipe title, ingredient name, author, URLs, and source-provided text untouched.

- [x] **Step 3: Add String Catalog source keys.**

  Add `IosAPP/ReciApp/Localizable.xcstrings` with English source values and translated catalog entries for all supported locales. Include interpolated keys with positional substitutions, not string concatenation.

  Current implementation has 215 source keys, including Share Extension copy and the default-folder fallback, with complete catalog coverage for the six canonical locales. Interpolated placeholders are validated across every locale.

- [ ] **Step 4: Verify UI localization.**

  Build, run the design preview, switch Settings from System default to Spanish, inspect accessibility labels, and confirm the app updates without relaunch.

### Task 3: Propagate language to server AI and cache

**Files:**
- Modify: `IosAPP/ReciApp/Models/Models.swift`
- Modify: `IosAPP/ReciApp/Services/APIClient.swift`
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`
- Create: `app/localization.py`
- Modify: `app/models.py`
- Modify: `app/main.py`
- Modify: `app/pipeline.py`
- Modify: `app/recipe_builder.py`
- Modify: `app/store.py`
- Create: `supabase/migrations/006_recipe_language.sql`
- Test: `tests/test_localization.py`

**Interfaces:**
- `ExtractRequest.language` is a string validated by `normalize_language`.
- `run_extract_job(..., language_code)` forwards the normalized code to `build_recipe(..., language_code)`.
- `get_recipe_by_norm(url_norm)` scopes extraction cache by normalized source URL. Missing target languages use one shared translation cache and one background job per recipe-language pair.

- [x] **Step 1: Add language request field and client propagation.**

  Encode `language` on every extraction request using the selected AppLanguage server code; preserve existing polling and error behavior.

- [x] **Step 2: Add server allowlist and normalization.**

  Accept exact supported codes and base-language fallback for regional device identifiers; return `en-US` for empty/unsupported values. Never interpolate unvalidated client text into the prompt.

- [x] **Step 3: Make prompt output target explicit.**

  Add translated description to the structured schema and require every user-facing recipe field to use the requested language while preserving proper nouns and source URLs.

- [x] **Step 4: Add language-aware extraction and shared translation cache.**

  Add language metadata, retain URL-only recipe uniqueness, and add `recipe_translations` plus translation-job uniqueness by `(recipe_id, language_code)`.

- [x] **Step 5: Add focused tests.**

  Test supported/unsupported normalization, request encoding, prompt target language, and that cache/active-job functions receive language scope without requiring live credentials.

### Task 4: Build, runtime, and source audit

**Files:**
- Verify: `IosAPP/ReciApp/**/*.swift`
- Verify: `app/**/*.py`
- Verify: `supabase/migrations/006_recipe_language.sql`

- [x] **Step 1: Run Python tests and static checks.**

  Run the focused localization assertions with the bundled Python runtime and compile the changed Python modules.

- [x] **Step 2: Run the iOS build.**

  Use the existing ReciApp scheme and a booted simulator; resolve compiler errors before UI inspection.

- [ ] **Step 3: Inspect localized Settings UI.**

  Capture screenshot and accessibility tree for System default and Spanish. Confirm no card strokes/borders were introduced.

  Spanish Home runtime was captured successfully. Full Settings/accessibility inspection remains pending because the Simulator host does not expose the embedded iOS accessibility tree in this environment.

- [x] **Step 4: Report integration boundary.**

  State clearly whether Supabase migration and authenticated server extraction were executed live; do not claim end-to-end AI proof from a local build alone.
