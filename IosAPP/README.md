# ReciApp iOS prototype

Local-only sketch app (parent repo ignores `IosAPP/`).

## Open

1. Open `ReciApp.xcodeproj` in Xcode
2. Select your Team → Signing & Capabilities
3. Bundle ID: `com.reciapp.dev` (or change to match Supabase Apple Client ID)
4. Add **Sign In with Apple** capability if missing
5. Run on device/simulator (Sign in with Apple works best on **real device**)

## Dev Pro (no Superwall)

`DevConfig.autoGrantPro = true` + `Secrets.swift` with Render `API_KEY` auto-patches user to Pro on login.

Copy `ReciApp/Config/Secrets.example.swift` → `Secrets.swift` if missing.

## Tabs

- **Recipes** — saved list from API
- **Import** — paste URL, extract, poll job
- **Profile** — quota, sign out, delete account

## Supabase Apple provider

Client ID in Supabase must match this app's Bundle ID.

## Backend

See `../IOS_INTEGRATION.md`
