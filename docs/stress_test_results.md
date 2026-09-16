# Stress test results (isolated stack)

Date: 2026-09-16
Target: VPS `reciapp-stress-*` on `127.0.0.1:18000` (not production)
Mode: `STRESS_TEST_MODE` mock, `STRESS_MOCK_LATENCY_MS=50`, `MAX_CONCURRENT_JOBS=64`
Cost: €0 (no OpenAI / no egress)

## Capacity verdict (soak 3 min/level)

| Level | Result | Realized | p95 POST | Notes |
|------:|:------:|---------:|--------:|-------|
| 10/s | PASS | ~600/min | ~21 ms | flat windows |
| 20/s | PASS | ~1200/min | ~19 ms | flat windows |
| 30/s | PASS | ~1790/min | ~17 ms | flat windows |
| 35/s | FAIL | ~2085/min | **1958 ms** | last 30s window queues (p95 1873, backlog) |

**Last sustained stable:** 30 recipes/s = **~1800 recipes/min** (3 min, ok_rate 1.0).

**Recommended with 30% margin:** 21 recipes/s = **~1260 recipes/min**.

Pass criteria: ok_rate≥0.98, p95&lt;5s, efficiency≥0.75, stable 30s windows, control request OK, no 5xx.

## Limits of this number

- Mock pipeline (no Whisper/OpenAI/yt-dlp). Real AI ceiling is much lower.
- Same VPS as prod (prod stayed healthy during soak).
- Artifact: `artifacts/20260916/soak-report.json`

## Cleanup

```bash
ssh ubuntu@51.255.43.100 'cd ~/reciapp-stress-src && docker compose -f docker-compose.stress.yml down'
# add -v only with explicit confirm
```
