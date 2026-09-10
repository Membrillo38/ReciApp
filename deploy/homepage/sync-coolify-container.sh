#!/usr/bin/env bash
# Keep Homepage "Recipe Backend" container name in sync with Coolify deploys.
set -euo pipefail

COOLIFY_NAME="${COOLIFY_NAME:-m6kbwmrfcknunjrnxbbsllca}"
SERVICES="${SERVICES:-/var/lib/reciapp/homepage/config/services.yaml}"

cid="$(docker ps --filter "label=coolify.name=${COOLIFY_NAME}" --format '{{.Names}}' | head -n1 || true)"
if [[ -z "${cid}" ]]; then
  echo "no running coolify app container for ${COOLIFY_NAME}" >&2
  exit 0
fi

tmp="$(mktemp)"
awk -v cid="$cid" '
  BEGIN { in_rb=0 }
  /^    - Recipe Backend:/ || /^    - ReciApp Dashboard:/ { in_rb=1; print; next }
  in_rb && /^        container:/ {
    print "        container: " cid
    in_rb=0
    next
  }
  in_rb && /^    - / { in_rb=0 }
  { print }
' "$SERVICES" > "$tmp"

if ! cmp -s "$tmp" "$SERVICES"; then
  mv "$tmp" "$SERVICES"
  echo "updated Recipe Backend container -> ${cid}"
else
  rm -f "$tmp"
fi
