#!/usr/bin/env bash
# E2E smoke: admin user → JWT → extract → poll job
set -euo pipefail

API="${API:-https://reciapp-4ih5.onrender.com}"
URL="${1:-https://vm.tiktok.com/ZGdQJr1J4/}"
API_KEY="${API_KEY:?Set API_KEY}"
SUPABASE_URL="${SUPABASE_URL:-https://nzimdcjxgklopythnpfi.supabase.co}"
SUPABASE_ANON="${SUPABASE_ANON:-eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im56aW1kY2p4Z2tsb3B5dGhucGZpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgzNjE1ODksImV4cCI6MjEwMzkzNzU4OX0._7_828Cs63M7tWLT83DYmtpAYP_8ptDg2Gr_4hRdzGM}"

EMAIL="e2e-$(date +%s)@reciapp.test"
PASS="$(openssl rand -base64 18)"

echo "== health =="
curl -fsS "$API/health"
echo

echo "== create user =="
curl -fsS -X POST "$API/v1/admin/users" \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\",\"display_name\":\"E2E\"}" | python3 -m json.tool

echo "== login =="
TOKEN=$(curl -fsS -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON" -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASS\"}" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
echo "token len ${#TOKEN}"

echo "== me =="
curl -fsS "$API/v1/me" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo "== extract $URL =="
JOB_JSON=$(curl -fsS -X POST "$API/v1/extract" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"url\":\"$URL\"}")
echo "$JOB_JSON" | python3 -m json.tool
JOB_ID=$(echo "$JOB_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")

echo "== poll job $JOB_ID =="
for i in $(seq 1 40); do
  R=$(curl -fsS "$API/v1/jobs/$JOB_ID" -H "Authorization: Bearer $TOKEN")
  STATUS=$(echo "$R" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  echo "poll $i: $STATUS"
  if [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ]; then
    echo "$R" | python3 -m json.tool
    [ "$STATUS" = "completed" ] || exit 1
    break
  fi
  sleep 3
done

echo "== my recipes =="
curl -fsS "$API/v1/me/recipes" -H "Authorization: Bearer $TOKEN" | python3 -m json.tool

echo "OK"
