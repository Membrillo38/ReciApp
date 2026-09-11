#!/usr/bin/env python3
"""Create an encrypted reset backup during a separately approved maintenance window."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from reset_guard import (
    RECEIPT_VERSION,
    ResetGuardError,
    load_json,
    validate_pg17,
    validate_pg_environment,
    validate_receipt_integrity,
    validate_target,
    validate_writer_evidence,
    write_receipt,
)


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, check=False, **kwargs)
    if result.returncode != 0:
        raise ResetGuardError(f"Backup tool failed: {command[0]}")
    return result


def _keychain_password(service: str, account: str) -> str:
    result = _run(
        ["security", "find-generic-password", "-w", "-s", service, "-a", account],
        capture_output=True,
        text=True,
    )
    password = result.stdout.rstrip("\n")
    if len(password) < 20:
        raise ResetGuardError("Keychain backup password is missing or too short")
    return password


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--writer-evidence", required=True, type=Path)
    parser.add_argument("--keychain-service", required=True)
    parser.add_argument("--keychain-account", required=True)
    args = parser.parse_args()

    validate_target(args.target_ref, args.target_host)
    validate_pg_environment(args.target_host)
    validate_pg17()
    preflight = load_json(args.preflight)
    validate_receipt_integrity(preflight)
    if preflight.get("target_ref") != args.target_ref or preflight.get("target_host") != args.target_host:
        raise ResetGuardError("Preflight targets another project")
    evidence = load_json(args.writer_evidence)
    validate_writer_evidence(evidence, target_ref=args.target_ref, target_host=args.target_host)
    evidence_digest = hashlib.sha256(args.writer_evidence.read_bytes()).hexdigest()
    if evidence_digest != preflight.get("writer_evidence_sha256"):
        raise ResetGuardError("Writer-freeze evidence changed since preflight")

    backup_root = Path.home() / "Documents" / "ReciApp Backups"
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup_root.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    encrypted = backup_root / f"reciapp-{args.target_ref}-{stamp}.tar.enc"
    receipt_path = encrypted.with_suffix(encrypted.suffix + ".receipt.json")
    password = _keychain_password(args.keychain_service, args.keychain_account)

    tempdir = Path(tempfile.mkdtemp(prefix="reciapp-reset-backup-", dir=backup_root))
    try:
        db_dump = tempdir / "database.dump"
        roles_dump = tempdir / "roles.sql"
        manifest = tempdir / "manifest.json"
        _run(["pg_dump", "--format=custom", "--no-owner", "--file", str(db_dump)])
        _run(["pg_dumpall", "--roles-only", "--file", str(roles_dump)])
        manifest.write_text(json.dumps({
            "version": RECEIPT_VERSION,
            "source_target_ref": args.target_ref,
            "preflight_receipt_sha256": preflight["receipt_sha256"],
            "snapshot": preflight["snapshot"],
            "external_dependencies_required": [
                "OAuth secrets and Apple provider keys inventory",
                "VPS environment and writer inventory",
            ],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        for path in (db_dump, roles_dump, manifest):
            path.chmod(0o600)

        archive = tempdir / "backup.tar"
        with tarfile.open(archive, "w") as tar:
            for path in (db_dump, roles_dump, manifest):
                tar.add(path, arcname=path.name, recursive=False)
        archive.chmod(0o600)

        child_env = dict(os.environ)
        child_env["RECIAPP_BACKUP_PASSWORD"] = password
        with encrypted.open("wb") as destination:
            encrypted.chmod(0o600)
            result = subprocess.run(
                [
                    "openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2",
                    "-iter", "250000", "-pass", "env:RECIAPP_BACKUP_PASSWORD",
                    "-in", str(archive),
                ],
                stdout=destination,
                stderr=subprocess.PIPE,
                env=child_env,
                check=False,
            )
        if result.returncode != 0 or not encrypted.is_file() or encrypted.stat().st_size == 0:
            encrypted.unlink(missing_ok=True)
            raise ResetGuardError("Backup encryption failed")
    finally:
        password = ""
        shutil.rmtree(tempdir, ignore_errors=True)

    digest = hashlib.sha256(encrypted.read_bytes()).hexdigest()
    write_receipt(receipt_path, {
        "version": RECEIPT_VERSION,
        "kind": "reciapp-encrypted-backup",
        "source_target_ref": args.target_ref,
        "source_target_host": args.target_host,
        "encrypted_backup": encrypted.name,
        "encrypted_backup_sha256": digest,
        "preflight_receipt_sha256": preflight["receipt_sha256"],
        "snapshot": preflight["snapshot"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"backup=ok encrypted={encrypted} receipt={receipt_path} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
