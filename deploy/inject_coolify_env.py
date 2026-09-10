#!/usr/bin/env python3
"""Inject /etc/reciapp/recipe-backend.env into Coolify application id=1."""
from __future__ import annotations

import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ENV_PATH = Path("/etc/reciapp/recipe-backend.env")
RESOURCE_TYPE = r"App\Models\Application"
RESOURCE_ID = 1

SECRET_KEYS = {
    "DATABASE_URL",
    "AUTH_JWT_SECRET",
    "API_KEY",
    "DASHBOARD_PASSWORD",
    "DASHBOARD_SESSION_SECRET",
    "DASHBOARD_TOTP_SECRET",
    "OPENAI_API_KEY",
    "REDIS_URL",
}


def esc(value: str) -> str:
    return value.replace("'", "''")


def main() -> None:
    pairs: list[tuple[str, str]] = []
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs.append((key.strip(), value))
    if not any(key == "PORT" for key, _ in pairs):
        pairs.append(("PORT", "8000"))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    stmts = [
        "BEGIN;",
        (
            "DELETE FROM environment_variables "
            f"WHERE resourceable_type = '{esc(RESOURCE_TYPE)}' "
            f"AND resourceable_id = {RESOURCE_ID};"
        ),
    ]
    for order, (key, value) in enumerate(pairs, start=1):
        uuid = secrets.token_hex(8)
        is_build = "false" if key in SECRET_KEYS else "true"
        stmts.append(
            "INSERT INTO environment_variables "
            "(key, value, is_preview, created_at, updated_at, is_shown_once, is_multiline, "
            "version, is_literal, uuid, \"order\", is_required, is_shared, "
            "resourceable_type, resourceable_id, is_runtime, is_buildtime, comment) VALUES ("
            f"'{esc(key)}', '{esc(value)}', false, '{now}', '{now}', false, false, "
            f"'4.0.0-beta.239', true, '{uuid}', {order}, false, false, "
            f"'{esc(RESOURCE_TYPE)}', {RESOURCE_ID}, true, {is_build}, NULL);"
        )
    stmts.append("COMMIT;")
    sql = "\n".join(stmts) + "\n"
    sql_path = Path("/tmp/coolify_env_inject.sql")
    sql_path.write_text(sql)
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "coolify-db",
            "psql",
            "-U",
            "coolify",
            "-d",
            "coolify",
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            "-",
        ],
        input=sql,
        text=True,
        check=True,
    )
    # Verify keys only
    verify = subprocess.check_output(
        [
            "docker",
            "exec",
            "coolify-db",
            "psql",
            "-U",
            "coolify",
            "-d",
            "coolify",
            "-tAc",
            (
                "SELECT key FROM environment_variables "
                f"WHERE resourceable_type = '{RESOURCE_TYPE}' "
                f"AND resourceable_id = {RESOURCE_ID} ORDER BY key;"
            ),
        ],
        text=True,
    )
    keys = [line.strip() for line in verify.splitlines() if line.strip()]
    print("injected_keys=" + ",".join(keys))
    print(f"count={len(keys)}")


if __name__ == "__main__":
    main()
