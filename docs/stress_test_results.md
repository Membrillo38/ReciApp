# Stress test results (isolated stack)

Date: 2026-09-16
Target: `127.0.0.1:18000` via SSH tunnel (VPS containers `reciapp-stress-*`)
Mock: `STRESS_MOCK_LATENCY_MS=50`, fail=0%, URLs `https://stress-test.local/recipe/N`
Prod: untouched (`51-255-43-100.sslip.io` health ok during/after)

## Summary

| Metric | Value |
|--------|-------|
| Maximum stable open-loop RPS | ~78 recipes/s accepted+completed |
| Degradation starts | ~98 RPS (p95 131→1322 ms, realized recipes/s 65→19) |
| Breaking point (errors/OOM) | Not reached in this window |
| Max concurrency tested | 250 simultaneous POSTs, ok_rate 1.0 |
| Peak burst recipes/s | ~30 at concurrency 25 |
| Primary bottleneck | App/queue backpressure under open-loop >~80 RPS (jobs still complete; latency/queue grow). Not Postgres CPU/RAM in this mock profile. |
| Recovery | Stress+prod healthy after runs; stress RAM ~75MB API / ~79MB PG |

## Concurrency (phase B)

| n | ok_rate | completed | p95 POST ms | recipes/s |
|--:|--------:|----------:|------------:|----------:|
| 1 | 1.0 | 1 | 138 | 4.7 |
| 10 | 1.0 | 10 | 232 | 17.2 |
| 25 | 1.0 | 25 | 352 | 30.1 |
| 50 | 1.0 | 50 | 607 | 28.9 |
| 100 | 1.0 | 100 | 770 | 28.0 |
| 250 | 1.0 | 250 | 750 | 21.4 |

## Open-loop RPS (phase C)

Stable through 78 RPS (p95 ~131 ms, ~65 recipes/s realized). At ~98 RPS: still 100% eventual completion but queueing dominates (p95 1322 ms, ~19 recipes/s).

## Safe production guidance (mock only)

These numbers are **mock pipeline + isolated DB**, not live OpenAI/yt-dlp. Do not copy as product caps for real extracts.

Suggested starting ops caps for similar hardware after real-provider soak:
- Sustained admission ≈ 50% of stable mock RPS → ~40 extract accepts/s only if provider latency≈50ms (unrealistic for real AI).
- Keep `MAX_CONCURRENT_JOBS=8` until real-provider soak; mock never stressed media/CPU path.

## Artifacts

- `artifacts/20260916/vps-20260916T125246Z/report.json`
- `artifacts/20260916/vps-20260916T125246Z-rps2/report.json`

## Cleanup (manual)

```bash
ssh ubuntu@51.255.43.100 'cd ~/reciapp-stress-src && docker compose -f docker-compose.stress.yml down'
# add -v only after explicit confirm to wipe stress DB volume
```
