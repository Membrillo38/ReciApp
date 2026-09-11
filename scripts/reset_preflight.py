#!/usr/bin/env python3
"""Read-only, fail-closed preflight for a later approved production reset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from reset_guard import (
    AUTH_DELETE_TABLES,
    AUTH_PRESERVE_TABLES,
    PUBLIC_DELETE_TABLES,
    PUBLIC_PRESERVE_TABLES,
    RECEIPT_VERSION,
    load_json,
    run_psql_json,
    validate_pg17,
    validate_pg_environment,
    validate_table_inventory,
    validate_target,
    validate_writer_evidence,
    write_receipt,
)


def _inventory_sql() -> str:
    target_rows = ", ".join(
        f"('{schema}', '{table}')"
        for schema, tables in (("public", PUBLIC_DELETE_TABLES), ("auth", AUTH_DELETE_TABLES))
        for table in tables
    )
    return f"""
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT json_build_object(
  'public', COALESCE((SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname = 'public'), '[]'::json),
  'auth', COALESCE((SELECT json_agg(tablename ORDER BY tablename) FROM pg_tables WHERE schemaname = 'auth'), '[]'::json),
  'dependencies', COALESCE((
    SELECT json_agg(source_schema || '.' || source_table || '->' || target_schema || '.' || target_table ORDER BY 1)
    FROM (
      SELECT ns.nspname source_schema, src.relname source_table,
             nt.nspname target_schema, dst.relname target_table
      FROM pg_constraint con
      JOIN pg_class src ON src.oid = con.conrelid
      JOIN pg_namespace ns ON ns.oid = src.relnamespace
      JOIN pg_class dst ON dst.oid = con.confrelid
      JOIN pg_namespace nt ON nt.oid = dst.relnamespace
      WHERE con.contype = 'f'
        AND (nt.nspname, dst.relname) IN ({target_rows})
    ) deps
  ), '[]'::json)
)::text;
COMMIT;
"""


def _snapshot_sql(inventory: dict[str, list[str]]) -> str:
    public_present = set(inventory.get("public") or [])
    auth_present = set(inventory.get("auth") or [])
    count_pairs = ",\n".join(
        f"    '{table}', (SELECT count(*) FROM public.{table})"
        for table in PUBLIC_DELETE_TABLES if table in public_present
    )
    auth_pairs = ",\n".join(
        f"    '{table}', (SELECT count(*) FROM auth.{table})"
        for table in AUTH_DELETE_TABLES if table in auth_present
    )
    config_parts = [
        f"COALESCE((SELECT jsonb_agg(to_jsonb(t)::text ORDER BY to_jsonb(t)::text)::text FROM auth.{table} t), '[]')"
        for table in AUTH_PRESERVE_TABLES if table in auth_present
    ]
    config_expression = " || ".join(config_parts) or "'[]'"
    return f"""
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT json_build_object(
  'server_version_num', current_setting('server_version_num'),
  'database', current_database(),
  'snapshot_id', pg_current_snapshot()::text,
  'captured_at', now(),
  'public_counts', json_build_object(
{count_pairs}
  ),
  'auth_counts', json_build_object(
{auth_pairs}
  ),
  'active_jobs', (SELECT count(*) FROM public.extract_jobs WHERE status IN ('pending', 'processing') OR lease_until > now()),
  'storage_objects', (SELECT CASE WHEN to_regclass('storage.objects') IS NULL THEN 0 ELSE (SELECT count(*) FROM storage.objects) END),
  'app_settings_fingerprint', encode(digest(COALESCE((SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id)::text FROM public.app_settings s), '[]'), 'sha256'), 'hex'),
  'schema_fingerprint', encode(digest(
    COALESCE((SELECT string_agg(table_schema || '.' || table_name || '.' || column_name || ':' || data_type || ':' || is_nullable || ':' || COALESCE(column_default, ''), E'\\n' ORDER BY table_schema, table_name, ordinal_position) FROM information_schema.columns WHERE table_schema IN ('public','auth')), '') ||
    COALESCE((SELECT string_agg(n.nspname || '.' || c.relname || ':' || con.conname || ':' || pg_get_constraintdef(con.oid), E'\\n' ORDER BY n.nspname, c.relname, con.conname) FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('public','auth')), '') ||
    COALESCE((SELECT string_agg(n.nspname || '.' || p.proname || ':' || pg_get_functiondef(p.oid), E'\\n' ORDER BY n.nspname, p.proname, p.oid) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname IN ('public','auth')), '') ||
    COALESCE((SELECT string_agg(schemaname || '.' || tablename || ':' || policyname || ':' || COALESCE(qual, '') || ':' || COALESCE(with_check, ''), E'\\n' ORDER BY schemaname, tablename, policyname) FROM pg_policies WHERE schemaname IN ('public','auth')), '') ||
    COALESCE((SELECT string_agg(extname || ':' || extversion, E'\\n' ORDER BY extname) FROM pg_extension), ''),
    'sha256'), 'hex'),
  'migration_fingerprint', encode(digest(COALESCE((SELECT string_agg(relname, E'\\n' ORDER BY relname) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind = 'r'), ''), 'sha256'), 'hex')
  , 'auth_config_fingerprint', encode(digest({config_expression}, 'sha256'), 'hex')
)::text;
COMMIT;
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--target-host", required=True)
    parser.add_argument("--writer-evidence", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    validate_target(args.target_ref, args.target_host)
    validate_pg_environment(args.target_host)
    validate_pg17()
    evidence = load_json(args.writer_evidence)
    validate_writer_evidence(evidence, target_ref=args.target_ref, target_host=args.target_host)
    inventory = run_psql_json(_inventory_sql())
    validate_table_inventory(inventory)
    snapshot = run_psql_json(_snapshot_sql(inventory))
    if snapshot.get("server_version_num", "0")[:2] != "17":
        raise RuntimeError("Target server must run PostgreSQL 17")
    if snapshot.get("active_jobs") != 0:
        raise RuntimeError("Preflight refuses nonzero pending/processing jobs or active leases")
    if snapshot.get("storage_objects") != 0:
        raise RuntimeError("Preflight refuses nonempty Storage; use the Storage API separately")

    write_receipt(args.output, {
        "version": RECEIPT_VERSION,
        "kind": "reciapp-reset-preflight",
        "target_ref": args.target_ref,
        "target_host": args.target_host,
        "writer_evidence_sha256": __import__("hashlib").sha256(args.writer_evidence.read_bytes()).hexdigest(),
        "continuous_write_freeze_required": True,
        "inventory": inventory,
        "snapshot": snapshot,
        "public_delete_allowlist": list(PUBLIC_DELETE_TABLES),
        "public_preserve_allowlist": list(PUBLIC_PRESERVE_TABLES),
        "auth_delete_allowlist": list(AUTH_DELETE_TABLES),
        "auth_preserve_allowlist": list(AUTH_PRESERVE_TABLES),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"preflight=ok receipt={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
