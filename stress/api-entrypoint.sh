#!/bin/sh
# Apply SQL migrations if schema missing, then start uvicorn.
set -eu

python - <<'PY'
import os, time, sys
import psycopg

url = os.environ["DATABASE_URL"]
for i in range(60):
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            with conn.cursor() as cur:
                cur.execute("select to_regclass('public.profiles')")
                exists = cur.fetchone()[0]
            if exists:
                print("migrations: schema present", flush=True)
                sys.exit(0)
            break
    except Exception as exc:
        print(f"wait postgres: {type(exc).__name__}", flush=True)
        time.sleep(1)
else:
    raise SystemExit("postgres not ready")

migrations = sorted(
    p for p in os.listdir("/app/migrations") if p.endswith(".sql")
)
with psycopg.connect(url, connect_timeout=10) as conn:
    conn.execute("select 1")
    for name in migrations:
        path = f"/app/migrations/{name}"
        print(f"migrations: apply {name}", flush=True)
        sql = open(path, encoding="utf-8").read()
        conn.execute(sql)
        conn.commit()
print("migrations: done", flush=True)
PY

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="${TRUSTED_PROXY_IPS}" --no-server-header
