#!/usr/bin/env bash
# Daily PostgreSQL backup for ReciApp VPS.
# Local retention: 7 daily / 4 weekly / 6 monthly.
# Off-site (Backblaze B2) is configured later; leave B2_* empty until then.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/reciapp/postgres}"
CONTAINER="${POSTGRES_CONTAINER:-reciapp-postgres}"
DB_USER="${POSTGRES_USER:-reciapp}"
DB_NAME="${POSTGRES_DB:-reciapp}"
LOG_FILE="${BACKUP_LOG:-/var/log/reciapp-postgres-backup.log}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
# Optional S3-compatible off-site (Backblaze B2). Skip when unset.
B2_BUCKET="${B2_BUCKET:-}"
B2_ENDPOINT="${B2_ENDPOINT:-}"
B2_ACCESS_KEY_ID="${B2_ACCESS_KEY_ID:-}"
B2_SECRET_ACCESS_KEY="${B2_SECRET_ACCESS_KEY:-}"
B2_SSE_PASSPHRASE_FILE="${B2_SSE_PASSPHRASE_FILE:-/etc/reciapp/secrets/backup_encryption_passphrase}"

umask 077
mkdir -p "$BACKUP_ROOT"/{daily,weekly,monthly}
touch "$LOG_FILE"

ts="$(date -u +%Y%m%dT%H%M%SZ)"
day="$(date -u +%Y-%m-%d)"
dow="$(date -u +%u)"   # 1=Mon … 7=Sun
dom="$(date -u +%d)"
outfile_base="reciapp-${ts}.sql.gz"
daily_path="$BACKUP_ROOT/daily/$outfile_base"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG_FILE"; }

notify() {
  local text="$1"
  if [[ -n "$TELEGRAM_BOT_TOKEN" && -n "$TELEGRAM_CHAT_ID" ]]; then
    curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=${text}" >/dev/null || true
  fi
}

fail() {
  log "ERROR: $*"
  notify "ReciApp backup FAILED: $*"
  exit 1
}

command -v docker >/dev/null || fail "docker missing"
docker inspect "$CONTAINER" >/dev/null 2>&1 || fail "container $CONTAINER missing"

log "START dump $outfile_base"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" --format=plain --no-owner --no-acl \
  | gzip -9 >"$daily_path.tmp"
mv "$daily_path.tmp" "$daily_path"

# Verify gzip and non-empty dump
gzip -t "$daily_path" || fail "gzip integrity failed"
size="$(wc -c <"$daily_path" | tr -d ' ')"
[[ "$size" -gt 100 ]] || fail "backup too small (${size} bytes)"

# Spot-check: gunzip header contains PostgreSQL dump marker
if ! gzip -dc "$daily_path" | head -c 200 | grep -q "PostgreSQL database dump"; then
  fail "dump header missing PostgreSQL marker"
fi
log "OK local daily size=${size}"

# Weekly copy on Sunday
if [[ "$dow" == "7" ]]; then
  cp -a "$daily_path" "$BACKUP_ROOT/weekly/reciapp-${day}.sql.gz"
fi
# Monthly copy on day 1
if [[ "$dom" == "01" ]]; then
  cp -a "$daily_path" "$BACKUP_ROOT/monthly/reciapp-${day}.sql.gz"
fi

# Retention (nullglob-safe)
shopt -s nullglob
daily_files=("$BACKUP_ROOT/daily"/*.sql.gz)
weekly_files=("$BACKUP_ROOT/weekly"/*.sql.gz)
monthly_files=("$BACKUP_ROOT/monthly"/*.sql.gz)
((${#daily_files[@]} > 7)) && printf '%s\n' "${daily_files[@]}" | sort -r | tail -n +8 | xargs -r rm -f
((${#weekly_files[@]} > 4)) && printf '%s\n' "${weekly_files[@]}" | sort -r | tail -n +5 | xargs -r rm -f
((${#monthly_files[@]} > 6)) && printf '%s\n' "${monthly_files[@]}" | sort -r | tail -n +7 | xargs -r rm -f
shopt -u nullglob

# Off-site encrypted copy when B2 credentials present
if [[ -n "$B2_BUCKET" && -n "$B2_ENDPOINT" && -n "$B2_ACCESS_KEY_ID" && -n "$B2_SECRET_ACCESS_KEY" ]]; then
  [[ -f "$B2_SSE_PASSPHRASE_FILE" ]] || fail "missing encryption passphrase file"
  enc_path="${daily_path}.gpg"
  gpg --batch --yes --symmetric --cipher-algo AES256 \
    --passphrase-file "$B2_SSE_PASSPHRASE_FILE" \
    -o "$enc_path" "$daily_path"
  export AWS_ACCESS_KEY_ID="$B2_ACCESS_KEY_ID"
  export AWS_SECRET_ACCESS_KEY="$B2_SECRET_ACCESS_KEY"
  aws --endpoint-url "$B2_ENDPOINT" s3 cp "$enc_path" "s3://${B2_BUCKET}/reciapp/postgres/${outfile_base}.gpg"
  rm -f "$enc_path"
  log "OK off-site B2 upload"
else
  log "SKIP off-site (B2 credentials not configured)"
fi

log "DONE"
notify "ReciApp backup OK ${outfile_base} (${size} bytes)"
