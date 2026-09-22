# Securitymaxxing checklist (millee.md reel)

Source: Instagram reel `DbMkXnBuTcb` — “Does your app have all these?” / Securitymaxxing vibecoded pt.2.

| # | Check from video | ReciApp server | Status |
|---|------------------|----------------|--------|
| 1 | Access controls so IDs in URL cannot steal data | `user_owns_recipe` / `user_can_access_job` on `/v1/recipes/{id}` and `/v1/jobs/{id}` | OK |
| 2 | API does not accept random browser origins | `CORSMiddleware` allowlist + admin `Origin` gate on `X-API-Key` | OK |
| 3 | Packages updated | `requirements.txt` pinned and CVE bumps present; run `pip-audit` in CI/release environment | Partial (scan not available in this checkout) |
| 4 | File uploads: type + size | No user upload API. Cover JPEGs: max 2MB + SOI magic + `.jpg` key | OK / N/A user upload |
| 5 | Parameterized DB queries | `psycopg` `%s` placeholders; no string-built SQL for user input | OK |
| 6 | Login tokens in secure cookies, not localStorage | Dashboard: password + mandatory TOTP; session is `HttpOnly` + `Secure` + `SameSite=Strict`. iOS: JWT in Keychain (client) | OK |
| 7 | Payment webhooks verified | Superwall Svix signature; Apple ASSN signed payload | OK |
| 8 | Basic security headers | HSTS, nosniff, DENY frame, Referrer-Policy, Permissions-Policy, CORP, COOP, CSP on `/dashboard`, `Cache-Control: no-store` on `/v1/` | OK |
| 9 | API does not return other people’s data | Ownership checks + RLS actor context | OK |
| 10 | 2FA on account / hosting / DB / domain | Dashboard TOTP enforced in code. Coolify + Postgres + registrar 2FA = **operator** (not code) | Partial |

## Operator 2FA (item 10)

Enable MFA on:

1. GitHub org / deploy bot account  
2. Coolify / VPS panel  
3. Postgres provider / host SSH keys (prefer keys over password; fail2ban)  
4. Domain registrar + DNS  

## Not in this reel (still required for App Store / GDPR)

Privacy Policy + Terms URLs in the iOS app / App Store Connect. Technical account deletion exists: `DELETE /v1/me`; legal copy, controller/contact details and external operator MFA cannot be honestly fabricated or enabled from this repository.
