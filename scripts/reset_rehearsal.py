#!/usr/bin/env python3
"""Restore an encrypted reset backup into an explicit disposable PostgreSQL 17 target."""

from __future__ import annotations

import argparse
import hashlib
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
    run_psql_json,
    validate_pg17,
    validate_receipt_integrity,
    validate_table_inventory,
    validate_target,
    write_receipt,
)
from reset_preflight import _inventory_sql, _snapshot_sql


def _checked(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, check=False, **kwargs)
    if result.returncode != 0:
        raise ResetGuardError(f"Rehearsal tool failed: {command[0]}")
    return result


def _safe_extract(archive: Path, destination: Path) -> None:
    allowed = {"database.dump", "roles.sql", "manifest.json"}
    with tarfile.open(archive, "r") as tar:
        names = {member.name for member in tar.getmembers() if member.isfile()}
        if names != allowed or any("/" in name or ".." in name for name in names):
            raise ResetGuardError("Encrypted backup contains an unexpected archive layout")
        tar.extractall(destination, filter="data")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--source-host", required=True)
    parser.add_argument("--rehearsal-host", required=True)
    parser.add_argument("--disposable-target", required=True)
    parser.add_argument("--encrypted-backup", required=True, type=Path)
    parser.add_argument("--backup-receipt", required=True, type=Path)
    parser.add_argument("--keychain-service", required=True)
    parser.add_argument("--keychain-account", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    validate_target(args.source_ref, args.source_host)
    if args.rehearsal_host == args.source_host or os.environ.get("PGHOST") != args.rehearsal_host:
        raise ResetGuardError("Rehearsal PGHOST must be explicit and different from production")
    if os.environ.get("PGSSLMODE") not in {"require", "verify-ca", "verify-full"}:
        raise ResetGuardError("PGSSLMODE must require TLS")
    validate_pg17()
    backup_receipt = load_json(args.backup_receipt)
    validate_receipt_integrity(backup_receipt)
    digest = hashlib.sha256(args.encrypted_backup.read_bytes()).hexdigest()
    if digest != backup_receipt.get("encrypted_backup_sha256"):
        raise ResetGuardError("Encrypted backup digest does not match its receipt")
    if backup_receipt.get("source_target_ref") != args.source_ref:
        raise ResetGuardError("Backup receipt belongs to another source project")

    key = _checked(
        ["security", "find-generic-password", "-w", "-s", args.keychain_service, "-a", args.keychain_account],
        capture_output=True,
        text=True,
    ).stdout.rstrip("\n")
    if len(key) < 20:
        raise ResetGuardError("Keychain backup password is missing or too short")

    tempdir = Path(tempfile.mkdtemp(prefix="reciapp-reset-rehearsal-"))
    try:
        archive = tempdir / "backup.tar"
        child_env = dict(os.environ)
        child_env["RECIAPP_BACKUP_PASSWORD"] = key
        with archive.open("wb") as output:
            result = subprocess.run(
                [
                    "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "250000",
                    "-pass", "env:RECIAPP_BACKUP_PASSWORD", "-in", str(args.encrypted_backup),
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                env=child_env,
                check=False,
            )
        if result.returncode != 0:
            raise ResetGuardError("Encrypted backup could not be decrypted")
        _safe_extract(archive, tempdir)
        _checked(["psql", "-X", "-v", "ON_ERROR_STOP=1", "-f", str(tempdir / "roles.sql")])
        _checked([
            "pg_restore", "--exit-on-error", "--clean", "--if-exists", "--no-owner",
            "--no-privileges", str(tempdir / "database.dump"),
        ])
        inventory = run_psql_json(_inventory_sql())
        validate_table_inventory(inventory)
        restored = run_psql_json(_snapshot_sql(inventory))
    finally:
        key = ""
        shutil.rmtree(tempdir, ignore_errors=True)

    expected = backup_receipt["snapshot"]
    comparisons = {
        "counts_match": restored.get("public_counts") == expected.get("public_counts") and restored.get("auth_counts") == expected.get("auth_counts"),
        "app_settings_match": restored.get("app_settings_fingerprint") == expected.get("app_settings_fingerprint"),
        "schema_fingerprint_match": restored.get("schema_fingerprint") == expected.get("schema_fingerprint"),
        "migration_fingerprint_match": restored.get("migration_fingerprint") == expected.get("migration_fingerprint"),
        "auth_config_match": restored.get("auth_config_fingerprint") == expected.get("auth_config_fingerprint"),
    }
    if not all(comparisons.values()):
        raise ResetGuardError(f"Restoration rehearsal comparison failed: {comparisons}")
    write_receipt(args.output, {
        "version": RECEIPT_VERSION,
        "kind": "reciapp-restoration-rehearsal",
        "source_target_ref": args.source_ref,
        "encrypted_backup_sha256": digest,
        "disposable_target": args.disposable_target,
        "decrypt_ok": True,
        "restore_exit_ok": True,
        **comparisons,
        "review_approved": False,
        "reviewed_by": None,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"rehearsal=ok review=pending receipt={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
