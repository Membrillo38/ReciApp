#!/usr/bin/env bash
# Keep 1 live Coolify app image + 1 previous. Idempotent. Root.
set -euo pipefail

KEEP_PREVIOUS="${KEEP_PREVIOUS:-1}"
APP_UUID="${APP_UUID:-m6kbwmrfcknunjrnxbbsllca}"
COOLIFY_KEEP="${COOLIFY_KEEP:-1}"

[[ "$(id -u)" -eq 0 ]] || exec sudo -E bash "$0" "$@"

if docker inspect coolify-db >/dev/null 2>&1; then
  docker exec coolify-db psql -U coolify -d coolify -v ON_ERROR_STOP=1 \
    -c "UPDATE application_settings SET docker_images_to_keep = ${COOLIFY_KEEP}, updated_at = NOW() WHERE docker_images_to_keep IS DISTINCT FROM ${COOLIFY_KEEP};" \
    >/dev/null
fi

declare -A keep=()
for cid in $(docker ps --filter "label=coolify.name=${APP_UUID}" --format '{{.ID}}'); do
  img="$(docker inspect -f '{{.Config.Image}}' "$cid")"
  keep["${img##*:}"]=1
done

prev=0
while read -r tag; do
  [[ -n "$tag" ]] || continue
  if [[ -n "${keep[$tag]:-}" ]]; then
    continue
  fi
  if [[ "$prev" -lt "$KEEP_PREVIOUS" ]]; then
    keep["$tag"]=1
    prev=$((prev + 1))
  fi
done < <(docker images --format '{{.CreatedAt}} {{.Tag}}' "$APP_UUID" | sort -r | awk '{print $NF}')

while read -r tag; do
  [[ -n "$tag" ]] || continue
  if [[ -z "${keep[$tag]:-}" ]]; then
    docker rmi "${APP_UUID}:${tag}" >/dev/null || true
  fi
done < <(docker images --format '{{.Tag}}' "$APP_UUID")

docker container prune -f >/dev/null
docker image prune -f >/dev/null
docker builder prune -f >/dev/null

kept="$(printf '%s ' "${!keep[@]}")"
echo "retention=ok keep=${kept} images=$(docker images -q "$APP_UUID" | wc -l | tr -d ' ')"
