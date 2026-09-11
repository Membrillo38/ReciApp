#!/usr/bin/env python3
"""Shared fail-closed guards for the later ReciApp reset procedure."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PUBLIC_DELETE_TABLES = (
    "api_request_logs",
    "apple_notification_events",
    "api_spend_ledger",
    "extract_job_access",
    "usage_events",
    "user_recipes",
    "subscription_events",
    "security_events",
    "spend_alerts",
    "extract_jobs",
    "recipe_translations",
    "recipes",
    "profiles",
)
PUBLIC_PRESERVE_TABLES = ("app_settings",)
AUTH_DELETE_TABLES = (
    "audit_log_entries",
    "flow_state",
    "hook_payloads",
    "identities",
    "mfa_amr_claims",
    "mfa_challenges",
    "mfa_factors",
    "oauth_authorization_codes",
    "oauth_authorizations",
    "oauth_client_states",
    "oauth_consents",
    "oauth_sessions",
    "one_time_tokens",
    "refresh_tokens",
    "saml_relay_states",
    "sessions",
    "users",
)
AUTH_PRESERVE_TABLES = (
    "instances",
    "oauth_clients",
    "saml_providers",
    "schema_migrations",
    "sso_domains",
    "sso_providers",
)
REQUIRED_WRITER_CONTROLS = (
    "all_backend_instances_maintenance",
    "background_workers_stopped",
    "auth_signups_disabled",
    "auth_session_refresh_frozen",
    "direct_data_api_writers_frozen",
    "cron_writers_frozen",
    "service_role_clients_frozen",
)
RECEIPT_VERSION = 1


class ResetGuardError(RuntimeError):
    pass


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResetGuardError(f"Invalid JSON receipt: {path.name}") from exc
    if not isinstance(value, dict):
        raise ResetGuardError(f"Receipt must be a JSON object: {path.name}")
    return value


def validate_receipt_integrity(receipt: dict[str, Any]) -> None:
    expected = receipt.get("receipt_sha256")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if not isinstance(expected, str) or expected != canonical_digest(body):
        raise ResetGuardError("Receipt digest is missing or invalid")


def validate_target(target_ref: str, target_host: str) -> None:
    if not re.fullmatch(r"[a-z0-9]([a-z0-9.-]{0,61}[a-z0-9])?", target_ref):
        raise ResetGuardError("Target ref must be a hostname label")
    blocked = ("supabase.co", "supabase.com", "onrender.com", "render.com")
    host = target_host.lower()
    if any(part in host for part in blocked):
        raise ResetGuardError("Target host must be self-hosted Postgres")
    if target_host != target_ref:
        raise ResetGuardError("Target host does not match the explicit project ref")


def validate_pg_environment(target_host: str) -> None:
    if any(arg.startswith("postgres") or "password=" in arg.lower() for arg in os.sys.argv[1:]):
        raise ResetGuardError("Database credentials/URLs are forbidden in command arguments")
    if os.environ.get("PGHOST") != target_host:
        raise ResetGuardError("PGHOST must exactly match --target-host")
    if not (os.environ.get("PGSERVICE") or (os.environ.get("PGUSER") and os.environ.get("PGDATABASE"))):
        raise ResetGuardError("Use PGSERVICE or PGHOST/PGUSER/PGDATABASE environment variables")
    sslmode = os.environ.get("PGSSLMODE", "")
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        raise ResetGuardError("PGSSLMODE must require TLS")


def validate_pg17(runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> None:
    for tool in ("psql", "pg_dump", "pg_dumpall", "pg_restore"):
        result = runner([tool, "--version"], capture_output=True, text=True, check=False)
        match = re.search(r"\b(\d+)(?:\.\d+)?\b", result.stdout or "")
        if result.returncode != 0 or not match or int(match.group(1)) != 17:
            raise ResetGuardError(f"{tool} major version 17 is required")


def validate_writer_evidence(
    evidence: dict[str, Any],
    *,
    target_ref: str,
    target_host: str,
    now: datetime | None = None,
) -> None:
    if evidence.get("target_ref") != target_ref or evidence.get("target_host") != target_host:
        raise ResetGuardError("Writer-freeze evidence targets another project")
    for name in REQUIRED_WRITER_CONTROLS:
        if evidence.get(name) is not True:
            raise ResetGuardError(f"Writer-freeze evidence missing control: {name}")
    if evidence.get("in_flight_processes") != 0:
        raise ResetGuardError("Writer-freeze evidence must show zero in-flight processes")
    if not str(evidence.get("reviewed_by") or "").strip():
        raise ResetGuardError("Writer-freeze evidence requires reviewed_by")
    try:
        observed = datetime.fromisoformat(str(evidence["observed_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise ResetGuardError("Writer-freeze evidence needs an ISO-8601 observed_at") from exc
    current = now or datetime.now(timezone.utc)
    if observed.tzinfo is None or abs((current - observed).total_seconds()) > 30 * 60:
        raise ResetGuardError("Writer-freeze evidence must be timezone-aware and no older than 30 minutes")


def validate_table_inventory(inventory: dict[str, list[str]]) -> None:
    public = set(inventory.get("public") or [])
    auth = set(inventory.get("auth") or [])
    expected_public = set(PUBLIC_DELETE_TABLES) | set(PUBLIC_PRESERVE_TABLES)
    missing_public = expected_public - public
    unknown_public = public - expected_public
    expected_auth = set(AUTH_DELETE_TABLES) | set(AUTH_PRESERVE_TABLES)
    missing_auth = ({"users", "identities", "sessions", "refresh_tokens"} - auth) if auth else set()
    unknown_auth = (auth - expected_auth) if auth else set()
    if missing_public or unknown_public or missing_auth or unknown_auth:
        raise ResetGuardError(
            "Unreviewed table inventory: "
            f"missing_public={sorted(missing_public)} unknown_public={sorted(unknown_public)} "
            f"missing_auth={sorted(missing_auth)} unknown_auth={sorted(unknown_auth)}"
        )
    # Every FK source that points at deleted data must itself be deleted. A
    # preserved or unknown table would otherwise retain data or block reset.
    allowed_sources = {
        *(f"public.{table}" for table in PUBLIC_DELETE_TABLES),
        *(f"auth.{table}" for table in AUTH_DELETE_TABLES),
    }
    unknown_dependencies = [
        value for value in (inventory.get("dependencies") or [])
        if str(value).split("->", 1)[0] not in allowed_sources
    ]
    if unknown_dependencies:
        raise ResetGuardError(f"Unreviewed dependent tables: {sorted(unknown_dependencies)}")


def validate_rehearsal_receipt(
    receipt: dict[str, Any],
    *,
    backup_sha256: str,
    target_ref: str,
) -> None:
    if receipt.get("version") != RECEIPT_VERSION:
        raise ResetGuardError("Unsupported rehearsal receipt version")
    if receipt.get("source_target_ref") != target_ref:
        raise ResetGuardError("Rehearsal receipt belongs to another source project")
    if receipt.get("encrypted_backup_sha256") != backup_sha256:
        raise ResetGuardError("Rehearsal receipt does not match the encrypted backup digest")
    required_true = (
        "decrypt_ok",
        "restore_exit_ok",
        "counts_match",
        "app_settings_match",
        "schema_fingerprint_match",
        "migration_fingerprint_match",
        "auth_config_match",
        "review_approved",
    )
    for field in required_true:
        if receipt.get(field) is not True:
            raise ResetGuardError(f"Rehearsal receipt failed gate: {field}")
    if not receipt.get("disposable_target") or not receipt.get("reviewed_by"):
        raise ResetGuardError("Rehearsal receipt lacks disposable target or reviewer")


def run_psql_json(
    sql: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> Any:
    result = runner(
        ["psql", "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-f", "-"],
        input=sql,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ResetGuardError("Database guard query failed; inspect redacted operator logs")
    try:
        return json.loads((result.stdout or "").strip())
    except json.JSONDecodeError as exc:
        raise ResetGuardError("Database guard query returned invalid JSON") from exc


def write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body["receipt_sha256"] = canonical_digest(payload)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
