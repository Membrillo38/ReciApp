# Share Videos to Recipes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Share TikTok, Instagram, YouTube, or Facebook links from iOS Share Sheet and have ReciApp open, import, extract, and save the recipe through the existing backend flow.

**Architecture:** The app registers `reciapp://` and decodes `reciapp://import?url=...` in its existing `.onOpenURL` path. A native Share Extension accepts `public.url` or `public.plain-text`, normalizes supported links, then opens the containing app; authentication and extraction remain owned by the main app and its existing `AppViewModel`.

**Tech Stack:** Swift 5, SwiftUI, UIKit Share Extension, UniformTypeIdentifiers, Xcode project file, existing FastAPI API.

**Spec:** `IOS_INTEGRATION.md` §3.3 and §3.6.

## Global Constraints

- Keep deployment target iOS 17.0.
- Keep bundle identifier `com.membri.reciapp`.
- Keep supported platforms TikTok, YouTube, Instagram, and Facebook.
- Keep remote recipe data authoritative; only local import handoff state may be persisted.
- Preserve existing unrelated working-tree changes.
- Do not place API keys or Supabase service credentials in the extension.

### Task 1: Main-app share URL handoff

**Files:**
- Modify: `IosAPP/ReciApp/ReciAppApp.swift`
- Modify: `IosAPP/ReciApp/ViewModels/AppViewModel.swift`
- Modify: `IosAPP/ReciApp/Services/URLNormalizer.swift`
- Modify: `IosAPP/ReciApp/Views/ImportView.swift`

**Interfaces:**
- Produce `AppViewModel.importFromIncomingURL(_ url: URL) async`.
- Consume the existing `importFromRaw(_:)`, `flushPendingImport()`, and `URLNormalizer.normalize(_:)` flow.

- [x] **Step 1: Add incoming URL decoding**

Implement `importFromIncomingURL(_:)` so `reciapp://import?url=<encoded-source-url>` extracts its `url` query item and forwards the source URL to `importFromRaw(_:)`; non-ReciApp URLs continue through unchanged.

- [x] **Step 2: Route SwiftUI open events through the decoder**

Replace the root `.onOpenURL` call to `importFromRaw(url.absoluteString)` with `importFromIncomingURL(url)`.

- [x] **Step 3: Persist pending imports while authentication is required**

Store the normalized pending URL under `reciapp.pendingImportURL.v1` when no token exists, restore it during initialization, clear it only after `flushPendingImport()` starts, and keep the existing sign-in-then-import behavior.

- [x] **Step 4: Explain Share Sheet use in the existing import sheet**

Add one compact line to `ImportView` stating that the user can use Share > ReciApp from TikTok, Instagram, YouTube, or Facebook; keep paste import unchanged.

- [x] **Step 5: Build the main app target**

Run `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO build` and fix only errors caused by this task.

### Task 2: Native Share Extension

**Files:**
- Create: `IosAPP/ReciAppShare/ShareViewController.swift`
- Create: `IosAPP/ReciAppShare/Info.plist`
- Modify: `IosAPP/ReciApp.xcodeproj/project.pbxproj`

**Interfaces:**
- `ShareViewController` consumes extension input providers for `public.url` and `public.plain-text`.
- `ShareViewController` produces `reciapp://import?url=...` for the containing app.

- [x] **Step 1: Read the shared URL or text item**

Use `NSItemProvider.loadItem(forTypeIdentifier:options:)` with `UTType.url.identifier` first and `UTType.plainText.identifier` second. Accept `URL` and `String` values, then pass the first supported value through `URLNormalizer.normalize(_:)`.

- [x] **Step 2: Open the containing app and finish the extension request**

Build the destination with `URLComponents`, query item name `url`, and scheme `reciapp`. Call `extensionContext?.open` and then `completeRequest`; show a short error alert and complete when no supported link is present.

- [x] **Step 3: Configure accepted Share Sheet content**

Set `NSExtensionPrincipalClass` to `$(PRODUCT_MODULE_NAME).ShareViewController`, `NSExtensionPointIdentifier` to `com.apple.share-services`, and activation rules for web URLs and plain text in `Info.plist`.

- [x] **Step 4: Add extension target wiring**

Add a `com.apple.product-type.app-extension` target named `ReciAppShare`, compile `ShareViewController.swift` and `URLNormalizer.swift`, embed `ReciAppShare.appex` in the app, and set bundle identifier `com.membri.reciapp.share`, product name, plist path, iOS 17 deployment, and automatic signing.

### Task 3: End-to-end verification

**Files:**
- Modify: `IosAPP/README.md` if manual Share Sheet setup needs documentation.

- [x] **Step 1: Validate project targets**

Run `xcodebuild -project IosAPP/ReciApp.xcodeproj -list` and confirm both `ReciApp` and `ReciAppShare` appear.

- [x] **Step 2: Build app and extension**

Run `xcodebuild -project IosAPP/ReciApp.xcodeproj -scheme ReciApp -sdk iphonesimulator -configuration Debug CODE_SIGNING_ALLOWED=NO build` and confirm both products compile.

- [x] **Step 3: Verify URL normalization cases**

Confirm `URLNormalizer.normalize` accepts representative TikTok, Instagram, YouTube, Facebook, `vm.tiktok.com`, and `youtu.be` links and rejects unrelated hosts.

- [ ] **Step 4: Verify cold and warm app handoff**

Launch the app once with a `reciapp://import?url=...` URL and once while it is already running; confirm the incoming source URL reaches the existing import state and pending import survives the unauthenticated path.

- [x] **Step 5: Report limits**

Report that real TikTok/Instagram/YouTube Share Sheet validation requires a signed device or simulator setup with the extension installed; backend extraction still depends on the existing authenticated API configuration.
