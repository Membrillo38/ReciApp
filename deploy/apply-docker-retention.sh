#!/usr/bin/env bash
# Install Coolify image retention (live + 1 previous) and prune now.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

[[ "$(id -u)" -eq 0 ]] || exec sudo -E bash "$0" "$@"

install -m 0755 "$ROOT/docker-image-retention.sh" /usr/local/sbin/reciapp-docker-image-retention.sh
install -m 0644 "$ROOT/docker-image-retention.cron" /etc/cron.d/reciapp-docker-image-retention
touch /var/log/reciapp-docker-retention.log
chmod 0644 /var/log/reciapp-docker-retention.log

/usr/local/sbin/reciapp-docker-image-retention.sh
