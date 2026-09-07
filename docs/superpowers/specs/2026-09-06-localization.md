# ReciApp localization and AI language spec

## Goal

ReciApp follows the device language by default, offers an explicit language override in Settings, supports 50 App Store language identifiers, and asks the server AI to generate each imported recipe in the selected language.

## Requirements

- The default app language is the device language when it is supported; otherwise English (U.S.).
- Settings contains a language picker with `System default` plus exactly 50 supported language options.
- Language choice persists locally and takes effect across the whole SwiftUI tree without relaunch.
- Existing folder-first navigation, visual style, account flow, and recipe data ownership remain unchanged.
- User-visible static copy uses the localization system; dynamic copy keeps pluralization and interpolation safe.
- `POST /v1/extract` accepts a validated BCP-47-like language identifier.
- Server recipe generation translates title, description, ingredients, units when appropriate, steps, tags, and missing-field labels to requested language; proper names, URLs, and source attribution remain intact.
- Recipe and active-job cache keys include normalized language so one URL can have one generated recipe per language.
- Existing recipes remain readable; existing rows migrate to English (U.S.) by default.
- No secrets or credentials enter logs or client code.

## Supported identifiers

`ar`, `bn`, `ca`, `zh-Hans`, `zh-Hant`, `hr`, `cs`, `da`, `nl`, `en-AU`, `en-CA`, `en-GB`, `en-US`, `fi`, `fr-FR`, `fr-CA`, `de`, `el`, `gu`, `he`, `hi`, `hu`, `id`, `it`, `ja`, `kn`, `ko`, `ms`, `ml`, `mr`, `nb`, `or`, `pl`, `pt-BR`, `pt-PT`, `pa`, `ro`, `ru`, `sk`, `sl`, `es-MX`, `es-ES`, `sv`, `ta`, `te`, `th`, `tr`, `uk`, `ur`, `vi`.

## Acceptance evidence

- Swift unit tests cover count, fallback, persistence, and request encoding.
- Python tests cover language normalization, prompt target language, and language-aware cache arguments.
- `xcodebuild` succeeds for the app scheme.
- Simulator screenshot/accessibility inspection shows Settings language picker and a non-English preview.
- Source audit confirms user-facing literals are either localization keys or intentional recipe/source content.
