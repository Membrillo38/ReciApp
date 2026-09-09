#!/usr/bin/env python3
"""Fail-closed reset executor. Default mode validates and performs no writes."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
from pathlib import Path

from reset_guard import (
    AUTH_DELETE_TABLES,
    PUBLIC_DELETE_TABLES,
    ResetGuardError,
    AUTH_PRESERVE_TABLES,
    load_json,
    run_psql_json,
    validate_pg17,
    validate_pg_environment,
    validate_receipt_integrity,
    validate_rehearsal_receipt,
    validate_table_inventory,
    validate_target,
    validate_writer_evidence,
)
from reset_preflight import _inventory_sql, _snapshot_sql


def build_reset_sql(
    *,
    public_tables: list[str],
    auth_tables: list[str],
    app_settings_fingerprint: str,
    migration_fingerprint: str,
    auth_config_fingerprint: str,
) -> str:
    allowed_public = [table for table in PUBLIC_DELETE_TABLES if table in public_tables]
    allowed_auth = [table for table in AUTH_DELETE_TABLES if table in auth_tables]
    for digest in (app_settings_fingerprint, migration_fingerprint, auth_config_fingerprint):
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ResetGuardError("Reset receipt contains an invalid fingerprint")
    deletes = [*(f"DELETE FROM public.{table};" for table in allowed_public), *(f"DELETE FROM auth.{table};" for table in allowed_auth)]
    locks = [*(f"LOCK TABLE public.{table} IN ACCESS EXCLUSIVE MODE;" for table in allowed_public), *(f"LOCK TABLE auth.{table} IN ACCESS EXCLUSIVE MODE;" for table in allowed_auth)]
    config_parts = [
        f"COALESCE((SELECT jsonb_agg(to_jsonb(t)::text ORDER BY to_jsonb(t)::text)::text FROM auth.{table} t), '[]')"
        for table in AUTH_PRESERVE_TABLES if table in auth_tables
    ]
    config_expression = " || ".join(config_parts) or "'[]'"
    zero_checks = " OR ".join(
        [*(f"EXISTS (SELECT 1 FROM public.{table})" for table in allowed_public), *(f"EXISTS (SELECT 1 FROM auth.{table})" for table in allowed_auth)]
    )
    return f"""
BEGIN;
SET LOCAL statement_timeout = '5min';
SET LOCAL lock_timeout = '10s';
{chr(10).join(locks)}
{chr(10).join(deletes)}
DO $reset_guard$
DECLARE
  settings_hash text;
  migrations_hash text;
  auth_config_hash text;
BEGIN
  IF {zero_checks} THEN
    RAISE EXCEPTION 'reset target tables are not empty';
  END IF;
  SELECT encode(digest(COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id)::text FROM public.app_settings s), '[]'), 'sha256'), 'hex') INTO settings_hash;
  SELECT encode(digest(COALESCE((SELECT string_agg(version, E'\\n' ORDER BY version) FROM supabase_migrations.schema_migrations), ''), 'sha256'), 'hex') INTO migrations_hash;
  SELECT encode(digest({config_expression}, 'sha256'), 'hex') INTO auth_config_hash;
  IF settings_hash <> '{app_settings_fingerprint}' OR migrations_hash <> '{migration_fingerprint}' OR auth_config_hash <> '{auth_config_fingerprint}' THEN
    RAISE EXCEPTION 'preserved settings, auth config, or migration history changed';
  END IF;
END
$reset_guard$;
COMMIT;
""".strip() + "\n"


def _execute_sql(sql: str) -> None:
    result = subprocess.run(
        ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=sql,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ResetGuardError("Reset transaction failed; commit status is not successful")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--writer-evidence", required=True, type=Path)
    parser.add_argument("--preflight", required=True, type=Path)
    parser.add_argument("--backup-receipt", required=True, type=Path)
    parser.add_argument("--rehearsal-receipt", required=True, type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args()

    validate_target(args.target_ref, args.target_host)
    validate_pg_environment(args.target_host)
    validate_pg17()
    evidence = load_json(args.writer_evidence)
    validate_writer_evidence(evidence, target_ref=args.target_ref, target_host=args.target_host)
    preflight = load_json(args.preflight)
    backup = load_json(args.backup_receipt)
    rehearsal = load_json(args.rehearsal_receipt)
    for receipt in (preflight, backup, rehearsal):
        validate_receipt_integrity(receipt)
    if preflight.get("target_ref") != args.target_ref or preflight.get("target_host") != args.target_host:
        raise ResetGuardError("Preflight targets another project")
    evidence_digest = hashlib.sha256(args.writer_evidence.read_bytes()).hexdigest()
    if evidence_digest != preflight.get("writer_evidence_sha256"):
        raise ResetGuardError("Continuous writer-freeze evidence changed after preflight")
    if backup.get("preflight_receipt_sha256") != preflight.get("receipt_sha256"):
        raise ResetGuardError("Backup was not produced from this preflight")
    backup_sha = str(backup.get("encrypted_backup_sha256") or "")
    validate_rehearsal_receipt(rehearsal, backup_sha256=backup_sha, target_ref=args.target_ref)

    inventory = run_psql_json(_inventory_sql())
    validate_table_inventory(inventory)
    current = run_psql_json(_snapshot_sql(inventory))
    if current.get("active_jobs") != 0 or current.get("storage_objects") != 0:
        raise ResetGuardError("Reset requires zero active jobs/leases and empty Storage")
    baseline = preflight["snapshot"]
    for field in ("app_settings_fingerprint", "schema_fingerprint", "migration_fingerprint", "auth_config_fingerprint"):
        if current.get(field) != baseline.get(field):
            raise ResetGuardError(f"Target changed after preflight: {field}")

    sql = build_reset_sql(
        public_tables=inventory["public"],
        auth_tables=inventory["auth"],
        app_settings_fingerprint=baseline["app_settings_fingerprint"],
        migration_fingerprint=baseline["migration_fingerprint"],
        auth_config_fingerprint=baseline["auth_config_fingerprint"],
    )
    expected_confirmation = f"RESET:{args.target_ref}:{backup_sha}"
    if not args.execute:
        print(f"reset=dry-run target_ref={args.target_ref} tables={len(PUBLIC_DELETE_TABLES) + len(AUTH_DELETE_TABLES)}")
        return 0
    if args.confirm != expected_confirmation:
        raise ResetGuardError("Execute confirmation does not match target ref and backup digest")
    _execute_sql(sql)
    print(f"reset=committed target_ref={args.target_ref}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
