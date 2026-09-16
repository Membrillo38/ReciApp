#!/usr/bin/env bash
# Stress harness entrypoint. Fails closed against production hosts.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

STRESS_BASE="${STRESS_BASE:-http://127.0.0.1:18000}"
STRESS_TOKEN="${STRESS_TOKEN:-stress-dev-token-change-me}"
STRESS_API_KEY="${STRESS_API_KEY:-stress-admin-key}"
STRESS_JWT_SECRET="${STRESS_JWT_SECRET:-stress-jwt-secret-not-for-prod-use-32b}"
STRESS_RUN_ID="${STRESS_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
export STRESS_BASE STRESS_TOKEN STRESS_API_KEY STRESS_JWT_SECRET STRESS_RUN_ID

case "$STRESS_BASE" in
  *51-255-43-100.sslip.io*|*onrender.com*|*supabase.co*)
    echo "refusing production host in STRESS_BASE=$STRESS_BASE" >&2
    exit 2
    ;;
esac

echo "== preflight curl =="
ready="$(curl -fsS -H "X-Stress-Token: $STRESS_TOKEN" "$STRESS_BASE/ready")"
echo "$ready" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("stress_test_mode") is True, d; print("stress_test_mode=true")'

OUT="artifacts/$(date -u +%Y%m%d)/$STRESS_RUN_ID"
mkdir -p "$OUT"

if command -v docker >/dev/null 2>&1; then
  echo "== collector snapshot =="
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' \
    reciapp-stress-api reciapp-stress-postgres >"$OUT/docker-stats-start.csv" || true
fi

echo "== campaigns =="
python3 "$ROOT/stress/runner.py" --base "$STRESS_BASE" --out "$OUT" "$@"

if command -v docker >/dev/null 2>&1; then
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}}' \
    reciapp-stress-api reciapp-stress-postgres >"$OUT/docker-stats-end.csv" || true
fi

echo "artifacts: $OUT"
echo "Done. Destroy stress volume only with explicit confirm (docker compose -f docker-compose.stress.yml down -v)."
