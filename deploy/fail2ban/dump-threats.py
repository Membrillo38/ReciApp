#!/usr/bin/env python3
"""Dump Fail2ban + recent SSH journal into security_events.fail2ban_snapshot."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

JAILS = ("sshd", "reciapp-probes", "recidive")
PASSWORD_FILE = Path("/etc/reciapp/secrets/postgres_password")


def _int_after(label: str, text: str) -> int:
    match = re.search(rf"{re.escape(label)}:\s+(\d+)", text)
    return int(match.group(1)) if match else 0


def parse_jail(text: str) -> dict:
    ips: list[str] = []
    match = re.search(r"Banned IP list:\s*(.*)$", text, re.MULTILINE)
    if match:
        ips = [part.strip() for part in match.group(1).split() if part.strip()]
    return {
        "currently_failed": _int_after("Currently failed", text),
        "total_failed": _int_after("Total failed", text),
        "currently_banned": _int_after("Currently banned", text),
        "total_banned": _int_after("Total banned", text),
        "banned_ips": ips,
    }


def jail_status(name: str) -> dict | None:
    try:
        text = subprocess.check_output(
            ["fail2ban-client", "status", name],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return parse_jail(text)


def ssh_recent(limit: int = 40) -> list[dict]:
    try:
        text = subprocess.check_output(
            [
                "journalctl",
                "-u",
                "ssh",
                "-u",
                "sshd",
                "--since",
                "24 hours ago",
                "-n",
                "200",
                "--no-pager",
                "-o",
                "short-iso",
            ],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    interesting = ("Failed", "Invalid user", "Connection closed by authenticating", "Ban ", "authentication failure")
    rows: list[dict] = []
    for line in text.splitlines():
        if not any(token in line for token in interesting):
            continue
        stamp, _, rest = line.partition(" ")
        rows.append({"t": stamp, "line": rest.strip()[:400] or line[:400]})
    return rows[-limit:]


def main() -> None:
    password = PASSWORD_FILE.read_text().strip()
    jails = {}
    for name in JAILS:
        parsed = jail_status(name)
        if parsed is not None:
            jails[name] = parsed
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "jails": jails,
        "ssh_recent": ssh_recent(),
    }
    raw = json.dumps(payload, separators=(",", ":"))
    sql = (
        "delete from security_events where event = 'fail2ban_snapshot';\n"
        "insert into security_events (event, metadata) values "
        f"('fail2ban_snapshot', $threat${raw}$threat$::jsonb);\n"
    )
    subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "-e",
            f"PGPASSWORD={password}",
            "reciapp-postgres",
            "psql",
            "-U",
            "reciapp",
            "-d",
            "reciapp",
            "-v",
            "ON_ERROR_STOP=1",
            "-q",
        ],
        input=sql,
        text=True,
        check=True,
    )


if __name__ == "__main__":
    main()
