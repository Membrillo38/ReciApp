#!/bin/bash
# Init stress DB from mounted migrations (first boot only).
set -euo pipefail
for f in /migrations/*.sql; do
  echo "Applying $f"
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -f "$f"
done
