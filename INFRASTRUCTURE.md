# ReciApp infrastructure (VPS)

Production host: `ubuntu@51.255.43.100` (Ubuntu 24.04, 4 vCPU, 8 GB RAM, 75 GB NVMe).

## Architecture

```
Internet
  |  22/tcp SSH (pubkey only)
  |  80/443 Coolify Traefik (recipe-backend HTTPS)
  v
VPS
  ├── Tailscale (100.123.33.15) — admin panels only
  │     ├── Coolify UI :8000
  │     ├── Uptime Kuma :3001
  │     └── Netdata :19999
  ├── coolify-proxy (Traefik) — public 80/443
  ├── recipe-backend — networks: coolify + reciapp-internal
  └── reciapp-postgres — reciapp-internal only (no host port)
```

Temporary public hostname: `https://51-255-43-100.sslip.io`  
Health: `/health` (liveness) · `/ready` (Postgres)

## Services

| Service | Where | Public? |
|---------|-------|---------|
| Recipe Backend | Docker `recipe-backend` | Yes (HTTPS via Traefik) |
| App Postgres | `reciapp-postgres` | No |
| Coolify | `coolify` + helpers | Tailscale only |
| Coolify's own Postgres/Redis | coolify network | No |
| Uptime Kuma | `uptime-kuma` | Tailscale `:3001` |
| Netdata | `netdata` | Tailscale `:19999` |
| Fail2ban | host | n/a |
| Backup cron | host `03:15 UTC` | n/a |

## Docker networks

- `reciapp-internal` — app DB + recipe-backend (private)
- `coolify` — Traefik + Coolify stack + recipe-backend (for routing labels)

**Important:** never use hostname `postgres` for the app DB (Coolify already owns that name). Use `reciapp-postgres`.

## Ports

Public: `22`, `80`, `443`  
Tailscale-bound: `8000` (Coolify), `3001` (Kuma), `19999` (Netdata), `6001/6002` (Coolify realtime)  
Not published: `5432` (reciapp-postgres)

UFW deny-incoming by default. `DOCKER-USER` drops non-80/443 Docker publishes from the public NIC (`ens3`). Persisted via `reciapp-docker-user-firewall.service`.

## Deployment

### Current (manual compose)

Sources on host: `/home/ubuntu/reciapp-src`  
Compose: `deploy/docker-compose.prod.yml`  
Env (root-only): `/etc/reciapp/recipe-backend.env`

```bash
cd /home/ubuntu/reciapp-src/deploy
sudo docker compose -f docker-compose.prod.yml build
sudo docker compose -f docker-compose.prod.yml up -d
curl -fsS https://51-255-43-100.sslip.io/ready
```

Hardening on recipe-backend: non-root image user, `no-new-privileges`, `cap_drop: ALL`, read-only root FS + tmpfs, memory/CPU/PID limits, healthcheck, log rotation. No docker.sock mount.

### Coolify + GitHub (target)

1. Open Coolify on Tailscale: `http://100.123.33.15:8000` and create the root account.
2. Connect GitHub repo `Membrillo38/ReciApp`.
3. Create Docker application:
   - Build pack: Dockerfile
   - Domain: `51-255-43-100.sslip.io` (or real domain later)
   - Health check path: `/health` (and verify `/ready` after deploy)
   - Attach network `reciapp-internal` (or set `DATABASE_URL` host `reciapp-postgres`)
   - Copy env vars from `/etc/reciapp/recipe-backend.env` into Coolify secrets (never commit them)
4. Webhook on push to `main` → build → healthcheck → swap.
5. Keep previous deployment for rollback in Coolify UI if health fails.

Until GitHub OAuth is connected in Coolify, use the manual compose path above.

## Required environment variables

See `.env.example`. Critical production keys live under `/etc/reciapp/secrets/` and `/etc/reciapp/recipe-backend.env`:

- `DATABASE_URL` → `postgresql://reciapp:***@reciapp-postgres:5432/reciapp`
- `AUTH_JWT_SECRET`
- `API_KEY`
- `OPENAI_API_KEY` (**must be set for extract**; currently empty until provided)
- Dashboard secrets, Apple bundle id, `TRUSTED_PROXY_IPS`, `PUBLIC_API_BASE_URL`, `CORS_ORIGINS`

## PostgreSQL

- Image: `postgres:16-alpine`
- Data: `/var/lib/reciapp/postgres`
- Schema: `migrations/001_init.sql` (self-hosted; no Supabase `auth.users`)
- Verify: `sudo docker exec reciapp-postgres pg_isready -U reciapp -d reciapp`

## Backups

Script: `/usr/local/sbin/reciapp-postgres-backup.sh` (repo: `deploy/postgres-backup.sh`)  
Cron: `/etc/cron.d/reciapp-postgres-backup` at **03:15 UTC**  
Local store: `/var/backups/reciapp/postgres/{daily,weekly,monthly}`  
Retention: 7 daily / 4 weekly / 6 monthly  
Logs: `/var/log/reciapp-postgres-backup.log`

Off-site Backblaze B2 is prepared in the script (`B2_*` env + GPG passphrase file). **Not configured yet — needs B2 keys.**

### Restore

```bash
# Stop writers (set MAINTENANCE_MODE=true / stop recipe-backend)
sudo docker stop recipe-backend
gzip -dc /var/backups/reciapp/postgres/daily/reciapp-YYYYMMDD….sql.gz \
  | sudo docker exec -i reciapp-postgres psql -U reciapp -d reciapp
sudo docker start recipe-backend
curl -fsS https://51-255-43-100.sslip.io/ready
```

### Periodic restore test

Monthly: restore latest daily dump into a throwaway container on `reciapp-internal`, run `SELECT count(*) FROM profiles`, then destroy the container. Record date in the ops log.

## Monitoring

- Uptime Kuma: `http://100.123.33.15:3001` — add monitors for `https://51-255-43-100.sslip.io/health`, `/ready`, and TCP check to `reciapp-postgres:5432` from an internal probe if desired.
- Netdata: `http://100.123.33.15:19999` — CPU/RAM/disk/containers.
- Fail2ban: `sudo fail2ban-client status sshd`

Telegram VPS Reporter: not deployed yet (needs bot token + authorized user id).

## Maintenance

```bash
# Updates
sudo apt update && sudo apt upgrade
sudo docker image prune -f

# Logs
sudo docker logs -f recipe-backend --tail 200
sudo docker logs -f reciapp-postgres --tail 100

# Backup now
sudo /usr/local/sbin/reciapp-postgres-backup.sh
```

## Add another isolated app later

1. Create a new Docker network `appX-internal`.
2. Run its DB (if any) only on that network, unique hostname, no host port.
3. Attach the app container to `appX-internal` + `coolify` for Traefik labels.
4. Bind any admin UI to Tailscale IP only.
5. Do not reuse the `postgres` hostname.
