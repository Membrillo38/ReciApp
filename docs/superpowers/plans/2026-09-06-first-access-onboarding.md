# First Access Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a small, account-scoped onboarding after first authenticated entry and persist Celsius/Fahrenheit plus Metric/Imperial preferences locally.

**Architecture:** `RootView` owns the one-time presentation gate because it already owns the auth-to-home transition. A small Codable preferences model and UserDefaults store keep the choices local and keyed by the Supabase user ID. A focused `OnboardingView` owns page state and returns completed preferences to the root.

**Tech Stack:** SwiftUI, UserDefaults, Codable, Supabase Auth session identity, iOS 17+

**Spec:** `docs/superpowers/specs/2026-09-06-first-access-onboarding.md`

## Global Constraints

- The onboarding appears only after an authenticated session is restored and only once per authenticated user.
- It asks for temperature preference: Celsius or Fahrenheit.
- It asks for measurement preference: Metric or Imperial.
- Preview mode continues directly to the existing design-preview home screen.
- Use ReciApp's solid light theme; do not add dependencies or Liquid Glass surfaces.
- Do not change the existing Apple sign-in flow or convert imported recipe quantities in this slice.

---

### Task 1: Add account-scoped preference storage

**Files:**
- Create: `IosAPP/ReciApp/Models/UserPreferences.swift`
- Modify: `IosAPP/ReciApp.xcodeproj/project.pbxproj` to include the new model source.
- Test: build validation in Task 4; the project has no XCTest target.

**Interfaces:**
- Produces `TemperatureUnit`, `MeasurementSystem`, `UserPreferences`, and `UserPreferencesStore` for the onboarding and root gate.

- [x] **Step 1: Define the preference values and Codable payload**

```swift
enum TemperatureUnit: String, Codable, CaseIterable {
    case celsius
    case fahrenheit
}

enum MeasurementSystem: String, Codable, CaseIterable {
    case metric
    case imperial
}

struct UserPreferences: Codable, Equatable {
    var temperatureUnit: TemperatureUnit = .celsius
    var measurementSystem: MeasurementSystem = .metric
}
```

- [x] **Step 2: Add the per-user UserDefaults store**

```swift
enum UserPreferencesStore {
    private static let keyPrefix = "reciapp.userPreferences.v1."

    static func isComplete(for userID: String) -> Bool {
        UserDefaults.standard.data(forKey: key(for: userID)) != nil
    }

    static func save(_ preferences: UserPreferences, for userID: String) {
        let data = try? JSONEncoder().encode(preferences)
        UserDefaults.standard.set(data, forKey: key(for: userID))
    }

    private static func key(for userID: String) -> String {
        keyPrefix + userID
    }
}
```

- [x] **Step 3: Compile the model with the existing project**

Run: `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug -derivedDataPath /private/tmp/ReciAppDerivedData CODE_SIGNING_ALLOWED=NO build`

Expected: `** BUILD SUCCEEDED **`.

### Task 2: Build the onboarding screen

**Files:**
- Create: `IosAPP/ReciApp/Views/OnboardingView.swift`
- Modify: `IosAPP/ReciApp.xcodeproj/project.pbxproj` to include the new view source.

**Interfaces:**
- Consumes `UserPreferences`.
- Produces `OnboardingView(preferences:onComplete:)`.

- [x] **Step 1: Create local state for the two pages**

```swift
@State private var page = 0
@State private var preferences: UserPreferences
```

- [x] **Step 2: Render the two preference questions**

Use solid `ReciTheme.canvas`, `ReciTheme.surface`, `ReciTheme.ink`, and `ReciTheme.orange` surfaces. Render two selectable buttons for each page, a page indicator, a Back button after page 0, a Continue button, and an `Omitir` action that completes with the current defaults.

- [x] **Step 3: Add accessible labels and stable state transitions**

Give each choice a descriptive accessibility label and mark the selected choice with a checkmark. Continue from temperature to measurement, then call `onComplete(preferences)` exactly once. Keep the onboarding full-screen and disable interactive dismissal so the explicit skip action remains the only bypass.

- [x] **Step 4: Build before wiring the root gate**

Run the same `xcodebuild` command from Task 1.

Expected: `** BUILD SUCCEEDED **`.

### Task 3: Present onboarding after first authenticated entry

**Files:**
- Modify: `IosAPP/ReciApp/ReciAppApp.swift:67-105`

**Interfaces:**
- Consumes `AuthService.session.user.id`, `UserPreferencesStore`, and `OnboardingView`.
- Keeps the existing `HomeView`, `LoginView`, design-preview path, refresh task, and Apple sign-in flow unchanged.

- [x] **Step 1: Add root-owned presentation state and account identity**

Add `@State private var showOnboarding = false` and derive the current user ID from the restored Supabase session. Use a task keyed by `hasRestoredSession` and user ID to set `showOnboarding` only when a signed-in user has no stored preferences.

- [x] **Step 2: Attach the full-screen onboarding to the authenticated home**

Present `OnboardingView(preferences: UserPreferences())` from the authenticated branch with `.fullScreenCover(isPresented: $showOnboarding)`. On completion, save using the current user ID and set `showOnboarding = false`. Do not attach this presentation to the debug design-preview branch.

- [x] **Step 3: Preserve account boundaries**

When auth becomes nil, reset `showOnboarding` to false. When a different user ID appears, rerun the gate and show onboarding only for that user's missing preference record.

- [x] **Step 4: Build the integrated flow**

Run: `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug -derivedDataPath /private/tmp/ReciAppDerivedData CODE_SIGNING_ALLOWED=NO build`

Expected: `** BUILD SUCCEEDED **`.

### Task 4: Verify first-entry behavior in Simulator

**Files:**
- Verify: `IosAPP/ReciApp/Views/OnboardingView.swift`
- Verify: `IosAPP/ReciApp/ReciAppApp.swift`
- Verify: `IosAPP/ReciApp/Models/UserPreferences.swift`

- [x] **Step 1: Install and launch the debug build**

Run: `xcrun simctl install 9DC99DE8-9D9D-4F44-A47C-5F6DE647E5FB /private/tmp/ReciAppDerivedData/Build/Products/Debug-iphonesimulator/ReciApp.app` and launch `com.membri.reciapp` without the design-preview argument.

Expected: the existing login screen remains unchanged when no authenticated session is present.

- [x] **Step 2: Verify the authenticated gate without changing Apple auth**

Use the existing design-preview launch only to confirm that `-reciapp-design-preview` still opens `HomeView` directly. Use accessibility inspection to confirm no onboarding is present in preview mode.

- [x] **Step 3: Verify the onboarding interaction**

Confirm the two questions, Celsius/Fahrenheit selection, Metric/Imperial selection, back navigation, skip action, final dismissal, and solid light presentation.

- [x] **Step 4: Verify persistence behavior**

After completing onboarding, relaunch the app with the same account/session and confirm the onboarding does not appear again. Confirm a missing account-scoped record would be eligible to show it without changing the existing home content.

The account-scoped load/save and root gate were verified in code and the onboarding was exercised through the DEBUG preview; a live Apple session was not available in the Simulator for a same-account relaunch.

- [x] **Step 5: Stop when acceptance passes**

Report the changed files, the stored preference behavior, and the build/runtime verification. Do not add recipe conversion or remote preference synchronization.
