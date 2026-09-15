# Stress ramp results (EXTRACT_DRY_RUN)

Date: 2026-09-15
Host: https://51-255-43-100.sslip.io
Hold: EXTRACT_DRY_RUN_HOLD_MS=500
Also raised during window: RATE_LIMIT_EXTRACT_PER_IP=5000, RATE_LIMIT_PER_IP=20000

## Completed levels

| Level | ok_rate | started_immediate | queued | completed | POST p95 ms | wall ms |
|------:|--------:|------------------:|-------:|----------:|------------:|--------:|
| 10 | 1.0 | 10 | 0 | 10 | 309 | 994 |
| 50 | 1.0 | 26 | 24 | 50 | 622 | 2587 |
| 100 | 1.0 | 66 | 34 | 100 | 495 | 2930 |

Notes:
- `started_immediate` can exceed `MAX_CONCURRENT_JOBS=8` because dry-run jobs finish in ~500ms and free slots during the same burst.
- True simultaneous processing ceiling remains 8 process slots; drain continues the rest.
- Level 200/1000 minting hit gateway 504 and then SSH to VPS timed out (likely host pressure / fail2ban). Re-run those levels after host recovers.

## Cliff

No cliff through 100 concurrent dry misses (ok_rate 1.0, all jobs completed).

## Caps decision (pending 200/1000)

Do **not** add `MAX_GLOBAL_OPEN_EXTRACT_JOBS` yet.
Keep `MAX_CONCURRENT_JOBS=8` until 200/1000 measured.
After full ramp: revisit global open-job ceiling and iOS Retry-After UX.
