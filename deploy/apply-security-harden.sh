#!/usr/bin/env bash
# Host hardening for ReciApp VPS. Idempotent. Does not close public SSH.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

install -d -m 0755 /data/coolify/proxy/dynamic
install -m 0644 "$ROOT/traefik/reciapp-hardening.yaml" /data/coolify/proxy/dynamic/reciapp-hardening.yaml

# Coolify UI must stay Tailscale-only (already bound on 100.123.33.15:8000).
# Traefik rejects `http: {}`; deleting the public router file is the valid form.
rm -f /data/coolify/proxy/dynamic/coolify-ui.yaml

install -m 0644 "$ROOT/fail2ban/filter.d/reciapp-probes.conf" /etc/fail2ban/filter.d/reciapp-probes.conf
install -m 0644 "$ROOT/fail2ban/jail.d/reciapp-probes.conf" /etc/fail2ban/jail.d/reciapp-probes.conf
install -m 0644 "$ROOT/logrotate/traefik-access" /etc/logrotate.d/traefik-access

touch /data/coolify/proxy/access.log
chmod 0644 /data/coolify/proxy/access.log

sshd_extra=/etc/ssh/sshd_config.d/99-hardening.conf
cat >"$sshd_extra" <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
ChallengeResponseAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthenticationMethods publickey
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding local
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 30
ClientAliveCountMax 2
EOF
sshd -t

compose=/data/coolify/proxy/docker-compose.yml
if [[ -f "$compose" ]] && ! grep -q 'accesslog.filepath' "$compose"; then
  python3 - <<'PY'
from pathlib import Path
p = Path("/data/coolify/proxy/docker-compose.yml")
text = p.read_text()
needle = "      - '--api.insecure=false'\n"
insert = (
    "      - '--api.insecure=false'\n"
    "      - '--api.dashboard=false'\n"
    "      - '--accesslog=true'\n"
    "      - '--accesslog.filepath=/traefik/access.log'\n"
    "      - '--accesslog.format=json'\n"
    "      - '--accesslog.bufferingsize=50'\n"
    "      - '--log.level=WARN'\n"
    "      - '--entrypoints.https.http.middlewares=reciapp-sec-headers@file'\n"
)
if needle in text and insert.strip().split("\n")[1] not in text:
    text = text.replace(needle, insert, 1)
# Drop public Traefik dashboard router labels if present.
out = []
skip_prefixes = (
    "      - traefik.http.routers.traefik.",
    "      - traefik.http.services.traefik.",
)
for line in text.splitlines(True):
    if any(line.startswith(p) for p in skip_prefixes):
        continue
    out.append(line)
p.write_text("".join(out))
PY
  cd /data/coolify/proxy
  docker compose up -d --force-recreate --no-deps traefik
fi

systemctl reload ssh || systemctl reload sshd
systemctl restart fail2ban

echo "harden applied"
curl -fsS --max-time 8 https://51-255-43-100.sslip.io/health
echo
