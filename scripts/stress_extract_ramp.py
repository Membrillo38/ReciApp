#!/usr/bin/env python3
"""Ramp concurrent dry-run extracts: N users, unique URLs, zero OpenAI.

Requires Coolify/env: EXTRACT_DRY_RUN=true (GET /ready must show extract_dry_run=true).
Optional for the window: raise RATE_LIMIT_EXTRACT_PER_IP_PER_MINUTE.

Env: API_KEY, AUTH_JWT_SECRET
Optional: API (default https://51-255-43-100.sslip.io)

Never prints tokens. Does not choose product max caps — only measures.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_LEVELS = (10, 50, 100, 200, 1000)
PROD_HOSTS = {"51-255-43-100.sslip.io"}


@dataclass(frozen=True)
class Hit:
    index: int
    status: int
    latency_ms: float
    queued: bool | None
    job_id: str | None
    code: str | None


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    body: dict | None = None,
    timeout: float = 120,
) -> tuple[int, dict | list | None, float]:
    raw = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=raw, headers=headers, method=method)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return int(resp.status), payload, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = None
        return int(exc.code), payload if isinstance(payload, (dict, list)) else None, (
            time.perf_counter() - started
        ) * 1000


def _mint_token(user_id: str, email: str, secret: str) -> str:
    import jwt

    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "email": email,
            "iss": "reciapp-api",
            "aud": "reciapp-ios",
            "iat": now,
            "exp": now + 3600,
        },
        secret,
        algorithm="HS256",
    )


def _require_dry_run(base: str) -> None:
    status, payload, _ = _request_json("GET", f"{base}/ready", headers={"Accept": "application/json"})
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError("ready_check_failed")
    if not payload.get("extract_dry_run"):
        raise RuntimeError(
            "EXTRACT_DRY_RUN is false on server. Set EXTRACT_DRY_RUN=true in Coolify, redeploy, retry."
        )


def _create_users(base: str, api_key: str, secret: str, count: int, stamp: str) -> list[str]:
    tokens: list[str] = []
    headers = {"X-API-Key": api_key, "Content-Type": "application/json", "Accept": "application/json"}
    for index in range(count):
        email = f"dry-{stamp}-{index}@reciapp.test"
        status, payload, _ = _request_json(
            "POST",
            f"{base}/v1/admin/users",
            headers=headers,
            body={"email": email, "display_name": f"Dry {index}", "is_pro": True},
        )
        if status not in {200, 201} or not isinstance(payload, dict):
            raise RuntimeError(f"admin_user_create_failed status={status}")
        items = payload.get("items") or []
        if not items:
            raise RuntimeError("admin_user_create_empty")
        tokens.append(_mint_token(str(items[0]["id"]), email, secret))
    return tokens


def _detail_code(payload: dict | list | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("code") or "") or None
    if isinstance(detail, str):
        return detail[:80]
    return None


def _extract(index: int, base: str, token: str, url: str, language: str) -> Hit:
    status, payload, latency = _request_json(
        "POST",
        f"{base}/v1/extract",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        body={"url": url, "language": language},
    )
    queued = None
    job_id = None
    if isinstance(payload, dict) and status < 400:
        queued = bool(payload.get("queued"))
        job_id = str(payload.get("job_id") or "") or None
    return Hit(index, status, latency, queued, job_id, _detail_code(payload))


def _poll_done(base: str, token: str, job_id: str, timeout_s: float) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status, payload, _ = _request_json(
            "GET",
            f"{base}/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30,
        )
        if status == 200 and isinstance(payload, dict):
            state = str(payload.get("status") or "")
            if state in {"completed", "failed"}:
                return state
        time.sleep(0.25)
    return "timeout"


def _summarize(level: int, hits: list[Hit], finals: dict[str, int], wall_ms: float) -> dict:
    latencies = [hit.latency_ms for hit in hits]
    accepted = [hit for hit in hits if hit.status < 400]
    p95 = (
        statistics.quantiles(latencies, n=100, method="inclusive")[94]
        if len(latencies) >= 2
        else (latencies[0] if latencies else 0.0)
    )
    by_status: dict[str, int] = {}
    for hit in hits:
        by_status[str(hit.status)] = by_status.get(str(hit.status), 0) + 1
    hint = None
    if any(hit.status == 429 for hit in hits):
        hint = "429s — often RATE_LIMIT_EXTRACT_PER_IP_PER_MINUTE; raise temporarily for ramp"
    return {
        "level": level,
        "requests": len(hits),
        "accepted": len(accepted),
        "queued": sum(1 for hit in accepted if hit.queued is True),
        "started_immediate": sum(1 for hit in accepted if hit.queued is False),
        "rejected": len(hits) - len(accepted),
        "by_status": by_status,
        "job_outcomes": finals,
        "ok_rate": (len(accepted) / len(hits)) if hits else 0.0,
        "wall_ms": wall_ms,
        "latency_ms": {
            "p50": statistics.median(latencies) if latencies else 0.0,
            "p95": p95,
            "max": max(latencies) if latencies else 0.0,
        },
        **({"hint": hint} if hint else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run extract ramp (zero OpenAI)")
    parser.add_argument("--api", default=os.environ.get("API", "https://51-255-43-100.sslip.io"))
    parser.add_argument("--levels", default=",".join(str(n) for n in DEFAULT_LEVELS))
    parser.add_argument("--language", default="en-US")
    parser.add_argument("--poll-timeout", type=float, default=180.0)
    parser.add_argument("--confirm-prod", action="store_true")
    parser.add_argument("--skip-poll", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("API_KEY", "").strip()
    secret = os.environ.get("AUTH_JWT_SECRET", "").strip()
    if not api_key or not secret:
        print("Set API_KEY and AUTH_JWT_SECRET", file=sys.stderr)
        return 2

    base = args.api.rstrip("/")
    host = (urlparse(base).hostname or "").lower()
    levels = tuple(int(part.strip()) for part in args.levels.split(",") if part.strip())
    if not levels or any(n < 1 for n in levels):
        print("Invalid --levels", file=sys.stderr)
        return 2
    if host in PROD_HOSTS and not args.confirm_prod:
        print("Production host requires --confirm-prod", file=sys.stderr)
        return 2

    try:
        _require_dry_run(base)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    stamp = str(int(time.time()))
    max_n = max(levels)
    print(json.dumps({"phase": "mint_users", "count": max_n, "host": host, "dry_run": True}, sort_keys=True))
    tokens = _create_users(base, api_key, secret, max_n, stamp)

    reports = []
    for level in levels:
        level_tokens = tokens[:level]
        urls = [f"https://youtu.be/dry{stamp}{i:05d}" for i in range(level)]
        wall_start = time.perf_counter()
        hits: list[Hit] = []
        with ThreadPoolExecutor(max_workers=min(level, 200)) as pool:
            futures = [
                pool.submit(_extract, idx, base, tok, url, args.language)
                for idx, (tok, url) in enumerate(zip(level_tokens, urls))
            ]
            for future in as_completed(futures):
                hits.append(future.result())
        hits.sort(key=lambda hit: hit.index)

        finals: dict[str, int] = {}
        if not args.skip_poll:
            with ThreadPoolExecutor(max_workers=min(level, 100)) as pool:
                poll_futures = []
                for hit, tok in zip(hits, level_tokens):
                    if hit.status < 400 and hit.job_id:
                        poll_futures.append(pool.submit(_poll_done, base, tok, hit.job_id, args.poll_timeout))
                for future in as_completed(poll_futures):
                    outcome = future.result()
                    finals[outcome] = finals.get(outcome, 0) + 1

        summary = _summarize(level, hits, finals, (time.perf_counter() - wall_start) * 1000)
        reports.append(summary)
        print(json.dumps({"phase": "level", **summary}, sort_keys=True))
        time.sleep(1.0)

    cliff = next((r["level"] for r in reports if r["ok_rate"] < 0.95), None)
    print(
        json.dumps(
            {
                "phase": "done",
                "cliff_level": cliff,
                "note": "Review Coolify CPU/RAM + these numbers before setting any MAX_* caps.",
                "levels": reports,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
