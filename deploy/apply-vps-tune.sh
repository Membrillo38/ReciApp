#!/usr/bin/env bash
# Host + Postgres + Redis tune for ReciApp VPS (8 GB RAM, NVMe).
# Idempotent. Run as ubuntu with passwordless sudo.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SYSCTL_SRC="${ROOT}/sysctl.d/99-reciapp.conf"
PG_SQL="${ROOT}/postgres-tune.sql"
REDIS_PASS_FILE="${REDIS_PASS_FILE:-/etc/reciapp/secrets/redis_password}"
ENV_FILE="${ENV_FILE:-/etc/reciapp/recipe-backend.env}"
REDIS_CONTAINER="${REDIS_CONTAINER:-reciapp-redis}"
PG_CONTAINER="${PG_CONTAINER:-reciapp-postgres}"

[[ "$(id -u)" -eq 0 ]] || exec sudo -E bash "$0" "$@"

install -m 644 "$SYSCTL_SRC" /etc/sysctl.d/99-reciapp.conf
sysctl -p /etc/sysctl.d/99-reciapp.conf >/dev/null

# Swap already exists (2G). Keep it; only lower swappiness.
swapon --show | grep -q . || {
  echo "swap missing" >&2
  exit 1
}

# No modem / no snaps on this VPS.
systemctl disable --now ModemManager.service 2>/dev/null || true
systemctl disable --now snapd.service snapd.socket snapd.seeded.service 2>/dev/null || true
systemctl mask ModemManager.service 2>/dev/null || true

umask 077
mkdir -p /etc/reciapp/secrets
if [[ ! -s "$REDIS_PASS_FILE" ]]; then
  openssl rand -base64 24 | tr -d '/+=' | head -c 32 > "$REDIS_PASS_FILE"
  chmod 600 "$REDIS_PASS_FILE"
fi
REDIS_PASS="$(cat "$REDIS_PASS_FILE")"
REDIS_URL="redis://:${REDIS_PASS}@${REDIS_CONTAINER}:6379/0"

if docker inspect "$REDIS_CONTAINER" >/dev/null 2>&1; then
  docker rm -f "$REDIS_CONTAINER" >/dev/null
fi
docker run -d \
  --name "$REDIS_CONTAINER" \
  --network reciapp-internal \
  --restart unless-stopped \
  --security-opt no-new-privileges:true \
  --memory 64m --cpus 0.25 --pids-limit 64 \
  --log-driver json-file --log-opt max-size=5m --log-opt max-file=2 \
  -e REDIS_PASSWORD="$REDIS_PASS" \
  redis:7-alpine \
  redis-server --save "" --appendonly no --maxmemory 48mb --maxmemory-policy allkeys-lru --requirepass "$REDIS_PASS" \
  >/dev/null
docker network connect coolify "$REDIS_CONTAINER" 2>/dev/null || true
docker exec "$REDIS_CONTAINER" redis-cli -a "$REDIS_PASS" --no-auth-warning ping | grep -q PONG

if [[ -f "$ENV_FILE" ]]; then
  if grep -q '^REDIS_URL=' "$ENV_FILE"; then
    sed -i "s|^REDIS_URL=.*|REDIS_URL=${REDIS_URL}|" "$ENV_FILE"
  else
    printf '\nREDIS_URL=%s\n' "$REDIS_URL" >> "$ENV_FILE"
  fi
  chmod 600 "$ENV_FILE"
fi

docker exec -i "$PG_CONTAINER" psql -U reciapp -d reciapp -v ON_ERROR_STOP=1 < "$PG_SQL"
docker restart "$PG_CONTAINER" >/dev/null
for _ in $(seq 1 20); do
  if docker exec "$PG_CONTAINER" pg_isready -U reciapp -d reciapp >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$PG_CONTAINER" pg_isready -U reciapp -d reciapp >/dev/null

echo "tune=ok swappiness=$(sysctl -n vm.swappiness) redis=$REDIS_CONTAINER postgres=$PG_CONTAINER"
