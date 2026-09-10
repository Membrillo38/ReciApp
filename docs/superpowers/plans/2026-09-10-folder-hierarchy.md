# Folder Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe arbitrary-depth folders, recipe drag/drop and bulk moves, plus independent persistent folder and recipe layouts.

**Architecture:** Keep recipes remote-authoritative and organization local. Add a pure hierarchy policy around globally unique folder names plus optional parent names, then persist that map beside existing assignments and colors. SwiftUI renders only children of the current folder, so the same screen recursively navigates every depth.

**Tech Stack:** Swift 6, SwiftUI, `UserDefaults` Codable snapshots, Swift Testing, iOS 17 drag/drop.

**Spec:** `docs/superpowers/specs/2026-09-10-folder-hierarchy.md`

## Global Constraints

- Deployment target remains iOS 17.0.
- No Supabase or Render mutation.
- No recipe deletion while moving or deleting folders.
- No Liquid Glass, borders, strokes, duplicate controls, or new tab navigation.
- Empty folders delete directly; non-empty folders move all recipes, never a partial destructive selection.

---

### Task 1: Hierarchy policy and compatibility migration

**Files:**
- Modify: `IosAPP/ReciApp/Services/ClientStatePolicy.swift`
- Modify: `IosAPP/ClientStateHarness/Sources/ClientStateHarness/ClientStatePolicy.swift`
- Test: `IosAPP/ClientStateHarness/Tests/ClientStateHarnessTests/ClientStatePolicyTests.swift`

**Interfaces:**
- Produces: `FolderHierarchyPolicy.sanitizedParents`, `canMove`, `moving`, `promotingChildren`, and `orderedChildren`.
- Consumes: folder names, `[String: String]` child-to-parent maps, and creation order.

- [x] **Step 1: Write failing policy tests**

```swift
@Test func hierarchyRejectsCyclesAndPromotesChildrenOnDelete() {
    let parents = ["Dinner": "Plans", "Plans": "Archive"]
    #expect(!FolderHierarchyPolicy.canMove("Archive", to: "Dinner", parents: parents))
    #expect(FolderHierarchyPolicy.promotingChildren(of: "Plans", parents: parents)["Dinner"] == "Archive")
}
```

- [x] **Step 2: Run tests and confirm missing-symbol failure**

Run: `swift test --package-path IosAPP/ClientStateHarness`

Expected: failure naming `FolderHierarchyPolicy`.

- [x] **Step 3: Implement deterministic hierarchy transforms**

```swift
enum FolderHierarchyPolicy {
    static func canMove(_ folder: String, to parent: String?, parents: [String: String]) -> Bool
    static func moving(_ folder: String, to parent: String?, parents: [String: String]) -> [String: String]?
    static func promotingChildren(of folder: String, parents: [String: String]) -> [String: String]
}
```

- [x] **Step 4: Mirror policy into harness and run tests**

Run: `swift test --package-path IosAPP/ClientStateHarness`

Expected: all tests pass.

### Task 2: Persistent view-model hierarchy

**Files:**
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`
- Modify: `IosAPP/ReciApp/Models/Models.swift`
- Test: `IosAPP/ClientStateHarness/Tests/ClientStateHarnessTests/ClientStatePolicyTests.swift`

**Interfaces:**
- Consumes: policy from Task 1.
- Produces: `categoryParents`, `childFolders(of:)`, `folderPath(_:)`, `moveCategory(_:to:)`, `canMoveCategory(_:to:)`, and recursive recipe lookup.

- [x] **Step 1: Add migration test**

```swift
@Test func flatFoldersMigrateToRootWithoutChangingAssignments() {
    #expect(FolderHierarchyPolicy.sanitizedParents(folders: ["A", "B"], parents: [:]).isEmpty)
}
```

- [x] **Step 2: Extend snapshot with optional parent data**

Decode absent `categoryParents` as `[:]`; save it on every organization mutation. Invalid parents and cycles are removed during load, preserving folders and assignments.

- [x] **Step 3: Add mutation APIs**

Creation rejects duplicate names. Rename rewrites assignments, color key, child parent values, and the renamed folder's parent key atomically before one save. Delete promotes children to the deleted folder's parent and reassigns only recipes still in the deleted folder.

- [x] **Step 4: Run package tests**

Run: `swift test --package-path IosAPP/ClientStateHarness`

Expected: all tests pass.

### Task 3: Recursive folders and editors

**Files:**
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`
- Modify: `IosAPP/ReciApp/Views/RecipeDetailView.swift`

**Interfaces:**
- Consumes: `childFolders(of:)`, `folderPath(_:)`, and safe hierarchy mutations.
- Produces: recursive navigation, create-subfolder action, parent picker, and move-folder action.

- [x] **Step 1: Render root children only on Home**

Keep `Uncategorized` at root. Folder tiles navigate using names and re-resolve current color/count from `AppViewModel`.

- [x] **Step 2: Render child folders inside folder screen**

The folder screen shows direct child folders before direct recipes. Selecting a child pushes the same `CategoryRecipesView` with its name.

- [x] **Step 3: Extend editor with parent destination**

Use a `Picker` that excludes the edited folder and descendants. Save calls `addCategory(..., parent:)` or atomic `updateCategory(..., parent:)` and keeps sheet open when validation fails.

- [x] **Step 4: Add accessible move-folder menu**

Context menu exposes `Move folder…` destinations filtered through `canMoveCategory`; no confirmation for reversible reparenting.

- [x] **Step 5: Build**

Run: `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug -derivedDataPath /tmp/ReciAppSubfolders CODE_SIGNING_ALLOWED=NO build`

Expected: `** BUILD SUCCEEDED **`.

### Task 4: Independent layouts, drag/drop, and bulk recipe movement

**Files:**
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`
- Modify: `IosAPP/ReciApp/Views/ProfileView.swift`

**Interfaces:**
- Consumes: existing single-save `moveRecipes(withIDs:to:)`.
- Produces: `CollectionLayout` preference, recipe `draggable`, folder `dropDestination`, selection set, and bulk destination sheet.

- [x] **Step 1: Add independent per-account preferences**

Use `reciapp.folderLayout.v1` and `reciapp.recipeLayout.v1`, each accepting `grid` or `list`. Existing `folderColumns` remains a grid density preference.

- [x] **Step 2: Render both layout variants**

Folder layout changes only folder containers. Recipe layout changes only recipe containers. Both reuse the same tile/row actions and stable recipe IDs.

- [x] **Step 3: Add recipe drag source and folder drop target**

Payload is recipe UUID text. Destination validates UUID, recipe existence, and changed folder before calling `setCategory`. `isTargeted` changes filled background and accessibility hint.

- [x] **Step 4: Add multi-selection move**

`Select` enters local selection mode. Selected IDs persist during navigation only until move/cancel. `Move selected` uses one folder destination menu and one `moveRecipes` persistence write.

- [x] **Step 5: Update Settings controls**

Expose separate Folder layout and Recipe layout pickers. Reset restores both to grid plus existing folder defaults.

- [x] **Step 6: Build and run tests**

Run: `swift test --package-path IosAPP/ClientStateHarness`

Run: `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug -derivedDataPath /tmp/ReciAppSubfolders CODE_SIGNING_ALLOWED=NO build`

Expected: tests pass and build succeeds.

### Task 5: Destructive safety and final verification

**Files:**
- Modify: `IosAPP/ReciApp/Views/HomeView.swift`
- Modify: `IosAPP/ReciApp/Localizable.xcstrings`
- Modify: `docs/superpowers/plans/2026-09-10-folder-hierarchy.md`

**Interfaces:**
- Consumes: recursive counts and child promotion from Tasks 1-2.
- Produces: final deletion behavior, user feedback, localization, and acceptance evidence.

- [x] **Step 1: Keep destructive deletion recipe-safe**

Empty direct folder deletion promotes children immediately. Non-empty deletion sheet counts direct recipes, moves all to chosen destination, promotes children, then removes folder.

- [x] **Step 2: Add concise validation and success copy**

Show duplicate, invalid move, and persistence errors inline. Success uses haptics and dismisses only after the model reports success.

- [x] **Step 3: Audit source**

Run: `rg -n "stroke|border" IosAPP/ReciApp/Views/HomeView.swift`

Expected: no new folder/recipe surface borders or strokes.

- [x] **Step 4: Run full focused verification**

Run: `swift test --package-path IosAPP/ClientStateHarness`

Run: `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug -derivedDataPath /tmp/ReciAppSubfolders CODE_SIGNING_ALLOWED=NO build`

Expected: all tests pass and build succeeds.

- [ ] **Step 5: Simulator QA when available**

Launch `com.membri.reciapp` with `-reciapp-design-preview`, inspect root and nested folder screens, change both layouts, move one recipe by menu and drag/drop, bulk-move selected recipes, reject a cycle, and delete a populated folder without losing recipes.

- [ ] **Step 6: Record outcome and complete Todoist task**

Check plan boxes backed by evidence. Complete Todoist task `6hV7G28H32qh392C` only after acceptance gates pass; otherwise leave it open with exact limitations.
