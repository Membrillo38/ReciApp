# First Access Onboarding Specification

## Goal

After the first authenticated entry, ReciApp asks for a small set of cooking preferences and saves them for that account.

## Acceptance criteria

- The onboarding appears only after an authenticated session is restored and only once per authenticated user.
- It asks for temperature preference: Celsius or Fahrenheit.
- It asks for measurement preference: Metric or Imperial.
- The user can move back, continue, skip, or finish.
- Preferences persist locally per Supabase user ID and are available for later personalization.
- Preview mode continues directly to the existing design-preview home screen.
- The onboarding uses ReciApp's solid light theme and does not add a new dependency or Liquid Glass surface.

## Non-goals

- Do not convert existing imported ingredient quantities or recipe text in this slice.
- Do not add a remote preferences table or API call.
- Do not change the existing Apple sign-in flow.
