#!/usr/bin/env python3
"""Sustained soak: find max recipes/min that stays healthy for N minutes."""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import create_users, one_extract, preflight, _pct  # noqa: E402


@dataclass
class Window:
    t0: float
    target_rps: float
    posted: int
    completed: int
    failed: int
    http_err: int
    p50: float
    p95: float
    p99: float
    realized_rps: float


def host_snapshot() -> dict:
    """Optional JSON from STRESS_HOST_SNAP file written by monitor."""
    path = os.environ.get("STRESS_HOST_SNAP", "/tmp/stress-snap.json")
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def main() -> int:
    base = os.environ.get("STRESS_BASE", "http://127.0.0.1:18000").rstrip("/")
    api_key = os.environ["STRESS_API_KEY"]
    secret = os.environ["STRESS_JWT_SECRET"]
    token = os.environ["STRESS_TOKEN"]
    soak_s = float(os.environ.get("SOAK_SECONDS", "180"))
    candidates = [float(x) for x in os.environ.get("RPS_CANDIDATES", "10,20,30,40,50,60").split(",")]
    users = int(os.environ.get("USERS", "120"))
    out = Path(os.environ.get("OUT", f"artifacts/soak-{int(time.time())}"))
    out.mkdir(parents=True, exist_ok=True)

    ready = preflight(base, token)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    tokens = create_users(base, api_key, secret, token, users, stamp)
    print(f"preflight ok users={len(tokens)} soak_s={soak_s} candidates={candidates}", flush=True)

    seq = 1
    results = []
    safe_rps = None
    fail_rps = None

    for target in candidates:
        print(f"\n=== SOAK target_rps={target:g} duration={soak_s}s ===", flush=True)
        # warm 10s
        warm_n = max(5, int(target * 10))
        with ThreadPoolExecutor(max_workers=min(100, max(8, int(target * 2)))) as pool:
            futs = [
                pool.submit(one_extract, base, tokens[i % len(tokens)], token, seq + i, wait=True)
                for i in range(warm_n)
            ]
            for _ in as_completed(futs):
                pass
        seq += warm_n
        time.sleep(2)

        deadline = time.perf_counter() + soak_s
        interval = 1.0 / target if target > 0 else 1.0
        hits_lat = []
        completed = failed = http_err = posted = 0
        windows: list[Window] = []
        win_t0 = time.perf_counter()
        win_posted = win_ok = win_fail = win_http = 0
        win_lats: list[float] = []
        workers = min(300, max(16, int(target * 4)))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            inflight = set()
            next_i = 0
            while time.perf_counter() < deadline:
                # submit one
                fut = pool.submit(
                    one_extract, base, tokens[next_i % len(tokens)], token, seq + next_i, wait=True
                )
                inflight.add(fut)
                next_i += 1
                posted += 1
                win_posted += 1
                time.sleep(interval)

                # collect finished
                done = {f for f in inflight if f.done()}
                for f in done:
                    inflight.remove(f)
                    h = f.result()
                    hits_lat.append(h.latency_ms)
                    win_lats.append(h.latency_ms)
                    if h.status < 200 or h.status >= 300:
                        http_err += 1
                        win_http += 1
                    elif h.final_status == "completed":
                        completed += 1
                        win_ok += 1
                    else:
                        failed += 1
                        win_fail += 1

                now = time.perf_counter()
                if now - win_t0 >= 30:
                    wall = now - win_t0
                    w = Window(
                        t0=win_t0,
                        target_rps=target,
                        posted=win_posted,
                        completed=win_ok,
                        failed=win_fail,
                        http_err=win_http,
                        p50=_pct(win_lats, 50),
                        p95=_pct(win_lats, 95),
                        p99=_pct(win_lats, 99),
                        realized_rps=win_ok / wall if wall else 0,
                    )
                    windows.append(w)
                    snap = host_snapshot()
                    print(
                        f"  win30 posted={w.posted} ok={w.completed} fail={w.failed} "
                        f"http_err={w.http_err} p95={w.p95:.0f} realized={w.realized_rps:.1f} "
                        f"host={snap}",
                        flush=True,
                    )
                    win_t0 = now
                    win_posted = win_ok = win_fail = win_http = 0
                    win_lats = []

            # drain
            for f in as_completed(inflight):
                h = f.result()
                hits_lat.append(h.latency_ms)
                if h.status < 200 or h.status >= 300:
                    http_err += 1
                elif h.final_status == "completed":
                    completed += 1
                else:
                    failed += 1

        seq += next_i
        wall = soak_s
        realized = completed / wall if wall else 0
        ok_rate = completed / max(1, posted)
        p95 = _pct(hits_lat, 95)
        eff = realized / target if target else 0
        snap = host_snapshot()

        # pass criteria for "normal" capacity
        win_ok_all = all(
            w.completed / max(1, w.posted) >= 0.98
            and w.p95 < 5000
            and w.realized_rps >= target * 0.75
            for w in windows
        ) if windows else False
        passed = (
            ok_rate >= 0.98
            and failed / max(1, posted) <= 0.02
            and http_err == 0
            and p95 < 5000
            and eff >= 0.75
            and win_ok_all
        )
        row = {
            "target_rps": target,
            "soak_s": soak_s,
            "posted": posted,
            "completed": completed,
            "failed": failed,
            "http_err": http_err,
            "ok_rate": ok_rate,
            "realized_rps": realized,
            "recipes_per_minute": realized * 60,
            "p50": _pct(hits_lat, 50),
            "p95": p95,
            "p99": _pct(hits_lat, 99),
            "efficiency": eff,
            "passed": passed,
            "windows": [asdict(w) for w in windows],
            "host_end": snap,
        }
        results.append(row)
        print(
            f"SOAK DONE target={target:g} passed={passed} ok_rate={ok_rate:.3f} "
            f"realized={realized:.2f}/s ({realized*60:.0f}/min) p95={p95:.0f} eff={eff:.2f}",
            flush=True,
        )

        # control + cooldown
        ctrl = one_extract(base, tokens[0], token, seq, wait=True)
        seq += 1
        print(f"CONTROL final={ctrl.final_status} ms={ctrl.latency_ms:.0f}", flush=True)
        if not passed or ctrl.final_status != "completed":
            fail_rps = target
            break
        safe_rps = target
        time.sleep(5)

    # safety margin 70% of last safe
    recommended = (safe_rps * 0.7) if safe_rps else 0
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": ready,
        "soak_seconds": soak_s,
        "last_safe_rps": safe_rps,
        "first_fail_rps": fail_rps,
        "recommended_rps": recommended,
        "recommended_recipes_per_minute": recommended * 60,
        "last_safe_recipes_per_minute": (safe_rps or 0) * 60,
        "criteria": {
            "ok_rate": ">=0.98",
            "p95_ms": "<5000",
            "efficiency": ">=0.75",
            "http_err": 0,
            "windows_30s": "all pass",
            "safety_margin": "0.7x last_safe",
        },
        "results": results,
    }
    path = out / "soak-report.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\nWROTE {path}", flush=True)
    print(
        f"VERDICT last_safe={safe_rps}/s ({(safe_rps or 0)*60:.0f}/min) "
        f"recommended={recommended:.1f}/s ({recommended*60:.0f}/min) "
        f"fail_at={fail_rps}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
