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


def _disposable_identity_sql() -> str:
    return """
SELECT json_build_object(
  'database', current_database(),
  'database_comment', (SELECT shobj_description(oid, 'pg_database') FROM pg_database WHERE datname = current_database()),
  'user_relation_count', (
    SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
      AND n.nspname !~ '^pg_toast' AND n.nspname !~ '^pg_temp'
      AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
  ),
  'nondefault_extension_count', (SELECT count(*) FROM pg_extension WHERE extname <> 'plpgsql')
)::text;
"""


def _validate_disposable_identity(
    identity: dict,
    *,
    expected_database: str,
    marker: str,
    require_empty: bool,
) -> None:
    if identity.get("database") != expected_database:
        raise ResetGuardError("Connected database does not match the explicit rehearsal database")
    if identity.get("database_comment") != f"reciapp-reset-disposable:{marker}":
        raise ResetGuardError("Rehearsal database lacks the exact disposable marker")
    if require_empty and (
        identity.get("user_relation_count") != 0
        or identity.get("nondefault_extension_count") != 0
    ):
        raise ResetGuardError("Rehearsal database must be new and empty before restore")


def _validate_rehearsal_host(*, source_host: str, rehearsal_host: str) -> None:
    if rehearsal_host == source_host or os.environ.get("PGHOST") != rehearsal_host:
        raise ResetGuardError("Rehearsal PGHOST must be explicit and different from production")


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
    parser.add_argument("--rehearsal-database", required=True)
    parser.add_argument("--encrypted-backup", required=True, type=Path)
    parser.add_argument("--backup-receipt", required=True, type=Path)
    parser.add_argument("--keychain-service", required=True)
    parser.add_argument("--keychain-account", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    validate_target(args.source_ref, args.source_host)
    _validate_rehearsal_host(
        source_host=args.source_host,
        rehearsal_host=args.rehearsal_host,
    )
    if os.environ.get("PGSSLMODE") not in {"require", "verify-ca", "verify-full"}:
        raise ResetGuardError("PGSSLMODE must require TLS")
    marker = os.environ.get("RECIAPP_DISPOSABLE_MARKER", "")
    if len(marker) < 32 or len(marker) > 128 or not marker.isalnum():
        raise ResetGuardError("RECIAPP_DISPOSABLE_MARKER must be 32-128 alphanumeric characters")
    validate_pg17()
    backup_receipt = load_json(args.backup_receipt)
    validate_receipt_integrity(backup_receipt)
    digest = hashlib.sha256(args.encrypted_backup.read_bytes()).hexdigest()
    if digest != backup_receipt.get("encrypted_backup_sha256"):
        raise ResetGuardError("Encrypted backup digest does not match its receipt")
    if backup_receipt.get("source_target_ref") != args.source_ref:
        raise ResetGuardError("Backup receipt belongs to another source project")

    initial_identity = run_psql_json(_disposable_identity_sql())
    _validate_disposable_identity(
        initial_identity,
        expected_database=args.rehearsal_database,
        marker=marker,
        require_empty=True,
    )

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
        restored_identity = run_psql_json(_disposable_identity_sql())
        _validate_disposable_identity(
            restored_identity,
            expected_database=args.rehearsal_database,
            marker=marker,
            require_empty=False,
        )
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
        "preflight_receipt_sha256": backup_receipt["preflight_receipt_sha256"],
        "disposable_target": f"{args.rehearsal_host}/{args.rehearsal_database}",
        "disposable_marker_sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
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
