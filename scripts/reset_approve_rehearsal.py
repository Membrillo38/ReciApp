#!/usr/bin/env python3
"""Bind a human post-restore review to an unapproved rehearsal receipt."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from reset_guard import ResetGuardError, load_json, validate_receipt_integrity, write_receipt


def approve_rehearsal(
    receipt: dict,
    *,
    reviewed_by: str,
    expected_disposable_target: str,
) -> dict:
    validate_receipt_integrity(receipt)
    if receipt.get("kind") != "reciapp-restoration-rehearsal":
        raise ResetGuardError("Approval input is not a restoration rehearsal receipt")
    if receipt.get("disposable_target") != expected_disposable_target:
        raise ResetGuardError("Disposable target does not match the reviewed rehearsal")
    reviewer = reviewed_by.strip()
    if not reviewer:
        raise ResetGuardError("Rehearsal approval requires a reviewer name")
    for field in (
        "decrypt_ok",
        "restore_exit_ok",
        "counts_match",
        "app_settings_match",
        "schema_fingerprint_match",
        "migration_fingerprint_match",
        "auth_config_match",
    ):
        if receipt.get(field) is not True:
            raise ResetGuardError(f"Cannot approve failed rehearsal gate: {field}")
    approved = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    approved.update({
        "review_approved": True,
        "reviewed_by": reviewer,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "unapproved_receipt_sha256": receipt["receipt_sha256"],
    })
    return approved


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--expected-disposable-target", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = approve_rehearsal(
        load_json(args.receipt),
        reviewed_by=args.reviewed_by,
        expected_disposable_target=args.expected_disposable_target,
    )
    write_receipt(args.output, payload)
    print(f"rehearsal_approval=ok receipt={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
