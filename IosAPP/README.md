# ReciApp iOS

Open `ReciApp.xcodeproj` in Xcode.

1. Select your Team → Signing & Capabilities
2. Bundle ID: `com.membri.reciapp` (must match the Apple Client ID in Supabase)
3. Confirm **Sign In with Apple**
4. Confirm App Group `group.com.membri.reciapp` on `ReciApp` and `ReciAppShare`

Run on a device for Sign in with Apple.

## Tabs

- **Recipes** — saved list from the API
- **Import** — paste a public TikTok, YouTube, Instagram, or Facebook URL
- **Profile** — quota, restore purchases, sign out, delete account

`is_pro` comes from `/v1/me`. The app never overwrites that from StoreKit or Superwall.

## Share videos

From TikTok, Instagram, YouTube, or Facebook, use Share → ReciApp. The extension writes the URL and language to the App Group. The main app creates the extract job. Links received while signed out wait until Sign in with Apple finishes.

## Backend

See `../INTEGRACION_SWIFT.md`
