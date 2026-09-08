"""Optional durable worker for extract_jobs.

Run this as a separate Render worker only after migration 011 is applied and
WORKER_ENABLED=true is configured on the web service. One process claims one
job at a time; Postgres leases make restarts and stale claims recoverable.
"""

from __future__ import annotations

import logging
import signal
from threading import Event
from uuid import UUID

from app.config import settings
from app.db import get_supabase, reset_supabase
from app.pipeline import run_extract_job, run_translation_job

logger = logging.getLogger(__name__)
_stop = Event()


def _handle_signal(signum: int, _frame) -> None:
    logger.info("worker stopping signal=%s", signum)
    _stop.set()


def _claim_next_job() -> dict | None:
    if settings.maintenance_mode:
        return None
    response = get_supabase().rpc(
        "claim_next_extract_job",
        {"p_lease_seconds": settings.worker_lease_seconds},
    ).execute()
    rows = response.data or []
    if isinstance(rows, dict):
        return rows
    return rows[0] if rows else None


def _run_claimed_job(row: dict) -> None:
    if settings.maintenance_mode:
        return
    job_id = UUID(str(row["id"]))
    user_id = UUID(str(row["user_id"]))
    kind = str(row.get("job_kind") or "extract")
    if kind == "translation":
        recipe_id = row.get("recipe_id")
        if not recipe_id:
            logger.error("worker invalid translation claim job_id=%s", job_id)
            return
        run_translation_job(
            job_id,
            user_id,
            UUID(str(recipe_id)),
            str(row.get("language_code") or "en-US"),
        )
        return
    if kind != "extract":
        logger.error("worker unsupported job kind job_id=%s kind=%s", job_id, kind)
        return
    run_extract_job(
        job_id,
        user_id,
        str(row["source_url_raw"]),
        str(row["source_url_norm"]),
        str(row.get("language_code") or "en-US"),
    )


def main() -> None:
    if not settings.worker_enabled:
        logger.info("worker disabled; set WORKER_ENABLED=true to run")
        return
    settings.validate_supabase()
    get_supabase()
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("worker started poll_seconds=%s lease_seconds=%s", settings.worker_poll_seconds, settings.worker_lease_seconds)
    try:
        while not _stop.is_set():
            try:
                row = _claim_next_job()
                if row:
                    _run_claimed_job(row)
                else:
                    _stop.wait(max(0.5, min(settings.worker_poll_seconds, 60.0)))
            except Exception as exc:
                # A transient database/network issue must not kill the worker. Do
                # not log exception text because providers can echo source data.
                logger.error(
                    "worker poll or job dispatch failed error_type=%s",
                    type(exc).__name__,
                )
                _stop.wait(max(1.0, min(settings.worker_poll_seconds, 60.0)))
    finally:
        reset_supabase()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
