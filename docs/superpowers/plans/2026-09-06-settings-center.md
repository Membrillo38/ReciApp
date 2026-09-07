# Settings Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn ReciApp Settings into a complete, polished control center for account, recipe preferences, folder layout, tactile feedback, data actions, and app information.

**Architecture:** Keep the existing custom `ScrollView` surface design in `ProfileView` so Settings matches the folder-first app. Persist account-scoped recipe preferences through `UserPreferencesStore`, keep device-only presentation preferences in `@AppStorage`, and extract repeated settings controls into small local views. Preserve the current haptic coordinator and no-border card rule.

**Tech Stack:** SwiftUI, `@AppStorage`, `UserDefaults`, existing `AuthService`, `AppViewModel`, and `UserPreferencesStore`.

**Spec:** User request in conversation: “mete en la app de settings todo, dejala perfecta”.

## Global Constraints

- Keep ReciApp folder-first and single-page; secondary flows may use sheets or alerts.
- Keep all cards without explicit borders or strokes; use filled surfaces, spacing, contrast, and subtle shadows only.
- Do not introduce Liquid Glass or unsupported account/network settings.
- Recipe preferences are saved per authenticated user; folder layout and haptics remain device-local.
- Preserve destructive actions behind confirmation and preserve existing refresh/auth behavior.
- Verify with a simulator build, launch, accessibility tree, and visual screenshot.

### Task 1: Wire persisted settings state

**Files:**
- Modify: `IosAPP/ReciApp/Views/ProfileView.swift`
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`
- Read/verify: `IosAPP/ReciApp/Models/UserPreferences.swift`

**Interfaces:**
- Consume existing `UserPreferencesStore.load(for:)` and `save(_:for:)`.
- Reuse the existing `reciapp.folderSort.v1`, `reciapp.folderColumns.v1`, and haptics storage keys.
- Expose `FolderSort` to Settings without changing its raw values or Home behavior.

- [x] Add local Settings state for the authenticated user's `UserPreferences`, load it when the user ID changes, and save only after the initial load completes.
- [x] Share the existing `FolderSort` type with `ProfileView` while preserving Home's current picker behavior.
- [x] Add bindings for temperature unit, measurement system, folder sorting, and folder columns that emit the existing selection haptic once per user change.

### Task 2: Build the complete Settings surface

**Files:**
- Modify: `IosAPP/ReciApp/Views/ProfileView.swift`

**Interfaces:**
- Keep the existing account, usage, refresh, haptics, sign-out, delete-account, and DEBUG actions functional.
- Add recipe preference controls, folder layout controls, reset layout action, and a compact About section.

- [x] Add a “Recipe preferences” surface with native segmented controls for Metric/Imperial and Celsius/Fahrenheit, showing the active values clearly.
- [x] Add a “Folder layout” surface with folder order and cards-per-row controls plus a reset action restoring Created/2 columns.
- [x] Keep Haptics in the experience area with its existing toggle and accessibility description.
- [x] Add an About surface reading the app version/build from `Bundle.main`, without fake links or unsupported claims.
- [x] Organize destructive account actions separately from neutral refresh/preferences actions.
- [x] Make all rows accessible, tappable, and visually consistent with the no-border card rule.

### Task 3: Validate behavior and visual quality

**Files:**
- Verify: `IosAPP/ReciApp/Views/ProfileView.swift`
- Verify: `IosAPP/ReciApp/Views/HomeView.swift`

- [ ] Run the full `xcodebuild` simulator build with signing disabled. Blocked by the pre-existing `SubscriptionService`/Superwall target integration in the shared ignored iOS workspace.
- [ ] Install and launch `com.membri.reciapp` with `-reciapp-design-preview`. Blocked until the target integration is repaired.
- [ ] Verify Settings accessibility labels/values and change Metric/Imperial, Celsius/Fahrenheit, folder layout, and Haptics. Source bindings and Swift parser pass; runtime blocked by the same target issue.
- [x] Return Haptics enabled and verify the source contains no card `.stroke`, `.border`, or `strokeBorder` calls.
- [ ] Inspect the Settings screenshot for clipping, duplicate controls, unintended borders, and consistent spacing. Runtime screenshot blocked by the same target issue.
