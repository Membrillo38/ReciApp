#!/usr/bin/env python3
"""Stress campaign runner: preflight, baseline, concurrency, adaptive RPS.

Targets only STRESS_TEST_MODE=true stacks. Never prints secrets.
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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROD_HOST_MARKERS = ("51-255-43-100.sslip.io", "onrender.com", "supabase.co")


@dataclass
class Hit:
    index: int
    status: int
    latency_ms: float
    job_id: str | None = None
    queued: bool | None = None
    code: str | None = None
    final_status: str | None = None
    poll_ms: float | None = None


@dataclass
class LevelResult:
    level: int | float
    kind: str
    ok_rate: float
    completed: int
    failed: int
    accepted: int
    post_p50_ms: float
    post_p95_ms: float
    post_p99_ms: float
    wall_ms: float
    recipes_per_sec: float
    errors: dict[str, int] = field(default_factory=dict)


def _now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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
    except Exception as exc:
        return 0, {"error": type(exc).__name__, "detail": str(exc)[:200]}, (time.perf_counter() - started) * 1000


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


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return ordered[idx]


def preflight(base: str, stress_token: str) -> dict:
    host = urlparse(base).hostname or ""
    if any(m in host for m in PROD_HOST_MARKERS):
        raise RuntimeError(f"refusing production host: {host}")
    status, payload, _ = _request_json(
        "GET",
        f"{base}/ready",
        headers={"Accept": "application/json", "X-Stress-Token": stress_token},
    )
    if status != 200 or not isinstance(payload, dict):
        raise RuntimeError(f"ready failed status={status} payload={payload}")
    if not payload.get("stress_test_mode"):
        raise RuntimeError("target is not STRESS_TEST_MODE=true")
    if str(payload.get("environment") or "").lower() not in {"stress", "stress-test"}:
        raise RuntimeError(f"unexpected environment={payload.get('environment')}")
    return payload


def create_users(base: str, api_key: str, secret: str, stress_token: str, count: int, stamp: str) -> list[str]:
    tokens: list[str] = []
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-API-Key": api_key,
        "X-Stress-Token": stress_token,
    }
    for i in range(count):
        email = f"stress-{stamp}-{i}@stress-test.local"
        status, payload, _ = _request_json(
            "POST",
            f"{base}/v1/admin/users",
            headers=headers,
            body={"email": email, "display_name": email, "is_pro": True},
        )
        if status not in (200, 201) or not isinstance(payload, dict):
            raise RuntimeError(f"user create failed status={status}")
        items = payload.get("items") or []
        if not items:
            raise RuntimeError("user create returned empty items")
        uid = str(items[0]["id"])
        tokens.append(_mint_token(uid, email, secret))
    return tokens


def poll_job(
    base: str,
    token: str,
    stress_token: str,
    job_id: str,
    *,
    timeout_s: float = 120,
) -> tuple[str, float]:
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Stress-Token": stress_token,
    }
    started = time.perf_counter()
    deadline = started + timeout_s
    last = "unknown"
    while time.perf_counter() < deadline:
        status, payload, _ = _request_json("GET", f"{base}/v1/jobs/{job_id}", headers=headers, timeout=30)
        if status == 200 and isinstance(payload, dict):
            last = str(payload.get("status") or "unknown")
            if last in {"completed", "failed"}:
                return last, (time.perf_counter() - started) * 1000
        time.sleep(0.15)
    return last, (time.perf_counter() - started) * 1000


def one_extract(
    base: str,
    token: str,
    stress_token: str,
    index: int,
    *,
    wait: bool,
) -> Hit:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "X-Stress-Token": stress_token,
        "X-Request-ID": f"stress-{index}",
    }
    url = f"https://stress-test.local/recipe/{index:06d}"
    status, payload, latency = _request_json(
        "POST",
        f"{base}/v1/extract",
        headers=headers,
        body={"url": url, "language": "en-US"},
        timeout=60,
    )
    job_id = None
    queued = None
    code = None
    if isinstance(payload, dict):
        job_id = str(payload.get("job_id") or "") or None
        queued = payload.get("queued")
        detail = payload.get("detail")
        if isinstance(detail, dict):
            code = str(detail.get("code") or detail.get("message") or "")[:80]
        elif isinstance(detail, str):
            code = detail[:80]
    hit = Hit(index=index, status=status, latency_ms=latency, job_id=job_id, queued=queued, code=code)
    if wait and job_id and 200 <= status < 300:
        final, poll_ms = poll_job(base, token, stress_token, job_id)
        hit.final_status = final
        hit.poll_ms = poll_ms
    return hit


def run_burst(
    *,
    base: str,
    tokens: list[str],
    stress_token: str,
    n: int,
    start_index: int,
    wait: bool,
    max_workers: int,
) -> tuple[list[Hit], float]:
    wall0 = time.perf_counter()
    hits: list[Hit] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = []
        for i in range(n):
            token = tokens[i % len(tokens)]
            futs.append(pool.submit(one_extract, base, token, stress_token, start_index + i, wait=wait))
        for fut in as_completed(futs):
            hits.append(fut.result())
    return hits, (time.perf_counter() - wall0) * 1000


def summarize(level: int | float, kind: str, hits: list[Hit], wall_ms: float) -> LevelResult:
    accepted = sum(1 for h in hits if 200 <= h.status < 300)
    completed = sum(1 for h in hits if h.final_status == "completed")
    failed = sum(1 for h in hits if h.final_status == "failed" or h.status >= 500 or h.status == 0)
    lat = [h.latency_ms for h in hits]
    errors: dict[str, int] = {}
    for h in hits:
        if h.status < 200 or h.status >= 300:
            key = f"http_{h.status}"
            errors[key] = errors.get(key, 0) + 1
        elif h.final_status == "failed":
            errors["job_failed"] = errors.get("job_failed", 0) + 1
    ok = completed if any(h.final_status for h in hits) else accepted
    denom = max(1, len(hits))
    rps = (ok / (wall_ms / 1000.0)) if wall_ms > 0 else 0.0
    return LevelResult(
        level=level,
        kind=kind,
        ok_rate=ok / denom,
        completed=completed,
        failed=failed,
        accepted=accepted,
        post_p50_ms=_pct(lat, 50),
        post_p95_ms=_pct(lat, 95),
        post_p99_ms=_pct(lat, 99),
        wall_ms=wall_ms,
        recipes_per_sec=rps,
        errors=errors,
    )


def stable(result: LevelResult, *, min_ok: float = 0.95, max_p95: float = 5000, min_efficiency: float = 0.45) -> bool:
    if result.ok_rate < min_ok:
        return False
    if result.post_p95_ms > max_p95:
        return False
    if result.failed > 0 and result.ok_rate < 0.99:
        return False
    # Open-loop target vs realized recipes/s — collapse = saturation even if jobs eventually finish.
    if result.kind == "rps" and isinstance(result.level, (int, float)) and result.level > 0:
        if result.recipes_per_sec < float(result.level) * min_efficiency:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=os.environ.get("STRESS_BASE", "http://127.0.0.1:18000"))
    parser.add_argument("--out", default="")
    parser.add_argument("--users", type=int, default=50)
    parser.add_argument("--concurrency-levels", default="1,2,5,10,25,50,100")
    parser.add_argument("--rps-start", type=float, default=1.0)
    parser.add_argument("--rps-max", type=float, default=80.0)
    parser.add_argument("--measure-seconds", type=float, default=20.0)
    parser.add_argument("--skip-rps", action="store_true")
    parser.add_argument("--skip-concurrency", action="store_true")
    args = parser.parse_args()

    api_key = os.environ.get("STRESS_API_KEY") or os.environ.get("API_KEY") or ""
    secret = os.environ.get("STRESS_JWT_SECRET") or os.environ.get("AUTH_JWT_SECRET") or ""
    stress_token = os.environ.get("STRESS_TOKEN") or ""
    if not api_key or not secret or not stress_token:
        print("Need STRESS_API_KEY, STRESS_JWT_SECRET, STRESS_TOKEN", file=sys.stderr)
        return 2

    base = args.base.rstrip("/")
    ready = preflight(base, stress_token)
    stamp = _now_id()
    run_id = os.environ.get("STRESS_RUN_ID") or stamp
    out_dir = Path(args.out or f"artifacts/{stamp}/{run_id}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"preflight ok stress_run_id={ready.get('stress_run_id')} env={ready.get('environment')}")
    tokens = create_users(base, api_key, secret, stress_token, args.users, stamp)
    print(f"users={len(tokens)}")

    results: list[dict[str, Any]] = []
    seq = 1

    # Phase A: sanity
    hit = one_extract(base, tokens[0], stress_token, seq, wait=True)
    seq += 1
    sanity = summarize(1, "sanity", [hit], hit.latency_ms + (hit.poll_ms or 0))
    results.append(asdict(sanity))
    print(f"sanity completed={hit.final_status} post_ms={hit.latency_ms:.0f} poll_ms={hit.poll_ms}")
    if hit.final_status != "completed":
        (out_dir / "report.json").write_text(json.dumps({"results": results, "error": "sanity_failed"}, indent=2))
        return 1

    # Phase B: concurrency
    if not args.skip_concurrency:
        levels = [int(x) for x in args.concurrency_levels.split(",") if x.strip()]
        for level in levels:
            workers = min(level, max(1, len(tokens)))
            hits, wall = run_burst(
                base=base,
                tokens=tokens,
                stress_token=stress_token,
                n=level,
                start_index=seq,
                wait=True,
                max_workers=workers,
            )
            seq += level
            summary = summarize(level, "concurrency", hits, wall)
            results.append(asdict(summary))
            print(
                f"concurrency n={level} ok_rate={summary.ok_rate:.3f} "
                f"completed={summary.completed} p95={summary.post_p95_ms:.0f} "
                f"recipes/s={summary.recipes_per_sec:.2f} wall_ms={summary.wall_ms:.0f}"
            )
            if not stable(summary) and level >= 50:
                print(f"stop concurrency sweep after unstable level={level}")
                break
            # host guard: brief pause
            time.sleep(1)

    # Phase C: adaptive open-loop RPS (approx via paced bursts)
    stable_limit = None
    degrade_at = None
    breaking = None
    if not args.skip_rps:
        rps = float(args.rps_start)
        while rps <= args.rps_max + 1e-9:
            duration = float(args.measure_seconds)
            total = max(1, int(rps * duration))
            interval = 1.0 / rps if rps > 0 else 1.0
            wall0 = time.perf_counter()
            hits: list[Hit] = []
            with ThreadPoolExecutor(max_workers=min(200, max(8, int(rps * 2)))) as pool:
                futs = []
                for i in range(total):
                    token = tokens[i % len(tokens)]
                    futs.append(
                        pool.submit(one_extract, base, token, stress_token, seq + i, wait=True)
                    )
                    time.sleep(interval)
                for fut in as_completed(futs):
                    hits.append(fut.result())
            seq += total
            wall = (time.perf_counter() - wall0) * 1000
            summary = summarize(rps, "rps", hits, wall)
            results.append(asdict(summary))
            print(
                f"rps={rps:g} ok_rate={summary.ok_rate:.3f} completed={summary.completed}/{total} "
                f"p95={summary.post_p95_ms:.0f} recipes/s={summary.recipes_per_sec:.2f}"
            )
            if stable(summary):
                stable_limit = rps
                rps = rps * 2 if rps < 8 else rps + max(2.0, rps * 0.25)
            else:
                if degrade_at is None:
                    degrade_at = rps
                if breaking is None and (summary.ok_rate < 0.8 or summary.post_p95_ms > 15000):
                    breaking = rps
                    break
                # binary-ish step down then stop exploration after first degrade bracket
                if stable_limit is not None:
                    mid = (stable_limit + rps) / 2
                    if abs(mid - rps) < 0.5:
                        break
                    rps = mid
                else:
                    break
            time.sleep(2)

    report = {
        "stress_run_id": run_id,
        "base": base,
        "ready": ready,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stable_limit_rps": stable_limit,
        "degradation_starts_rps": degrade_at,
        "breaking_point_rps": breaking,
        "results": results,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "manifest.json").write_text(
        json.dumps(
            {
                "stress_run_id": run_id,
                "base": base,
                "users": len(tokens),
                "artifact_dir": str(out_dir),
            },
            indent=2,
        )
    )
    print(f"wrote {out_dir / 'report.json'}")
    print(
        f"SUMMARY stable_limit={stable_limit} degradation_starts={degrade_at} "
        f"breaking_point={breaking}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
