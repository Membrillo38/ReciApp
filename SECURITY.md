# ReciApp security

## SSH

- Pubkey only (`AuthenticationMethods publickey`)
- `PasswordAuthentication no` (fixed cloud-init first-wins via `/etc/ssh/sshd_config.d/50-cloud-init.conf` + `99-hardening.conf`)
- Root password login disabled (`PermitRootLogin prohibit-password`; root account locked)
- Fail2ban jail `sshd` enabled
- Verify before tightening: second SSH session with pubkey; keep an open session while reloading `sshd`

## Firewall

- UFW: default deny incoming; allow `22`, `80`, `443`, and all on `tailscale0`
- Docker bypass mitigation: `DOCKER-USER` chain drops published container ports from public NIC except `80`/`443`
- Persisted by systemd unit `reciapp-docker-user-firewall.service`
- Coolify UI / Kuma / Netdata bound to Tailscale IP `100.123.33.15`, not `0.0.0.0`
- Traefik dashboard host port `8080` removed from coolify-proxy

## Docker hardening (Recipe Backend)

- Non-root user in image
- `no-new-privileges`
- `cap_drop: ALL`
- Read-only root filesystem + tmpfs for `/tmp`
- Memory / CPU / PID limits
- Healthcheck on `/health`
- `restart: unless-stopped`
- JSON log rotation
- Never: `privileged`, host `/`, or `/var/run/docker.sock` on recipe-backend
- Netdata alone mounts docker.sock read-only for container metrics (admin Tailscale only)

## SSRF

`app/security.py`:

- Only `http`/`https`, ports `80`/`443`
- DNS resolve before connect; re-validate every redirect
- Block loopback, private, link-local, multicast, reserved, unspecified, metadata hosts
- Max 5 redirects; bounded downloads via `safe_urlopen_limited`
- yt-dlp invoked with argument lists only (`shell=False`); URL validated first

## Rate limiting and bans

- General `/v1/*`: 180/IP/min, 120/user/min (defaults)
- Extract: 15/IP/min, 10/user/min, plus daily user cap
- Exceed → HTTP `429` + `Retry-After`; expensive work not started
- Temporary ban ladder on repeated limit hits: 5 minutes → 1 hour → 24 hours (never permanent auto-ban)
- `/health` and `/ready` exempt

## Trusted proxies

- `TRUSTED_PROXY_IPS` gates `X-Forwarded-For`
- Untrusted clients: use `request.client.host` only
- Uvicorn `--forwarded-allow-ips` must not be `*`

## Secrets

- Host files under `/etc/reciapp/secrets/` and `/etc/reciapp/recipe-backend.env` (mode `600`, root)
- Never commit API keys, DB passwords, JWT secrets, Telegram tokens, Tailscale keys, Coolify tokens
- Do not print full secrets in logs or chat

## PostgreSQL

- Private Docker network only; no host `5432` publish
- Strong random password in `/etc/reciapp/secrets/postgres_password`
- App connects as role `reciapp` via `DATABASE_URL`
- Schema without Supabase Auth; local JWT + Apple Sign-In

## Backups

- Daily compressed dumps with integrity checks
- Off-site B2 path encrypts with GPG before upload (credentials not installed yet)
- Alert hook ready for Telegram when token configured
- Test restores monthly on a disposable container

## Incident response (basic)

1. **Lockdown:** confirm SSH access; if compromised key, remove from `authorized_keys` from console/Tailscale.
2. **Contain:** `sudo docker stop recipe-backend`; set `MAINTENANCE_MODE=true` if needed.
3. **Assess:** `docker logs`, Fail2ban bans, Netdata, Uptime Kuma, `/var/log/auth.log`.
4. **Rotate:** DB password, `AUTH_JWT_SECRET`, `API_KEY`, OpenAI key, dashboard secrets; recreate env and containers.
5. **Restore:** from last known-good backup if data integrity uncertain.
6. **Reopen:** verify `/health` + `/ready`, then resume traffic.

Report abuse patterns (5xx/429 spikes, SSH brute force) via Kuma/Netdata/Telegram once reporter is live.
