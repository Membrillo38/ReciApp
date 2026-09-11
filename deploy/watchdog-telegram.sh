#!/usr/bin/env bash
# Alert Telegram if a ReciApp dependency stays down >= 5 minutes.
# Tokens: /etc/reciapp/secrets/telegram_bot_token and telegram_chat_id
set -euo pipefail

DOWN_SECONDS="${DOWN_SECONDS:-300}"
STATE_DIR="${STATE_DIR:-/var/lib/reciapp/watchdog}"
API_BASE="${API_BASE:-https://51-255-43-100.sslip.io}"
TOKEN_FILE="${TOKEN_FILE:-/etc/reciapp/secrets/telegram_bot_token}"
CHAT_FILE="${CHAT_FILE:-/etc/reciapp/secrets/telegram_chat_id}"
COOLIFY_NAME="${COOLIFY_NAME:-m6kbwmrfcknunjrnxbbsllca}"

mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"

notify() {
  local text="$1"
  local token chat
  token="$(cat "$TOKEN_FILE" 2>/dev/null || true)"
  chat="$(cat "$CHAT_FILE" 2>/dev/null || true)"
  [[ -n "$token" && -n "$chat" ]] || return 0
  curl -fsS -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    --data-urlencode "chat_id=${chat}" \
    --data-urlencode "text=${text}" >/dev/null || true
}

fail_tick() {
  local name="$1"
  local msg="$2"
  local now since
  now="$(date +%s)"
  if [[ ! -f "$STATE_DIR/$name.since" ]]; then
    echo "$now" >"$STATE_DIR/$name.since"
  fi
  since="$(cat "$STATE_DIR/$name.since")"
  if (( now - since >= DOWN_SECONDS )) && [[ ! -f "$STATE_DIR/$name.alerted" ]]; then
    notify "ReciApp DOWN (>$((DOWN_SECONDS / 60)) min): $msg"
    touch "$STATE_DIR/$name.alerted"
  fi
}

ok_tick() {
  local name="$1"
  local msg="$2"
  if [[ -f "$STATE_DIR/$name.alerted" ]]; then
    notify "ReciApp UP: $msg"
  fi
  rm -f "$STATE_DIR/$name.since" "$STATE_DIR/$name.alerted"
}

check_http() {
  local name="$1"
  local url="$2"
  local expect="$3"
  local body code
  code="$(curl -sS -o /tmp/reciapp-watchdog-body -w "%{http_code}" --max-time 8 "$url" || echo 000)"
  body="$(tr -d '\n' </tmp/reciapp-watchdog-body 2>/dev/null || true)"
  if [[ "$code" == "200" && "$body" == *"$expect"* ]]; then
    ok_tick "$name" "$url"
  else
    fail_tick "$name" "$url HTTP $code"
  fi
}

check_container() {
  local name="$1"
  local filter="$2"
  local cid status
  cid="$(docker ps -q --filter "$filter" | head -n1 || true)"
  if [[ -z "$cid" ]]; then
    fail_tick "$name" "container missing ($filter)"
    return
  fi
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid")"
  if [[ "$status" == "healthy" || "$status" == "running" ]]; then
    ok_tick "$name" "$filter $status"
  else
    fail_tick "$name" "$filter $status"
  fi
}

if [[ "${1:-}" == "--test" ]]; then
  notify "ReciApp watchdog activo. Aviso si algo cae más de $((DOWN_SECONDS / 60)) min."
  exit 0
fi

check_http api-health "$API_BASE/health" '"status":"ok"'
check_http api-ready "$API_BASE/ready" '"status":"ready"'
check_container postgres "name=reciapp-postgres"
check_container redis "name=reciapp-redis"
check_container proxy "name=coolify-proxy"
check_container backend "label=coolify.name=${COOLIFY_NAME}"
