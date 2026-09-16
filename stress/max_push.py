#!/usr/bin/env python3
"""Push until hard cliff: errors, timeouts, host pressure, or throughput collapse."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

# Reuse runner primitives
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import (  # noqa: E402
    Hit,
    create_users,
    one_extract,
    preflight,
    run_burst,
    summarize,
    _now_id,
)


def host_guard_ssh() -> dict:
    """Best-effort local check via STRESS_HOST_JSON env (collector injects)."""
    raw = os.environ.get("STRESS_HOST_JSON")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def main() -> int:
    base = os.environ.get("STRESS_BASE", "http://127.0.0.1:18000").rstrip("/")
    api_key = os.environ["STRESS_API_KEY"]
    secret = os.environ["STRESS_JWT_SECRET"]
    token = os.environ["STRESS_TOKEN"]
    out = Path(os.environ.get("OUT", f"artifacts/{_now_id()}/max-push"))
    out.mkdir(parents=True, exist_ok=True)

    ready = preflight(base, token)
    stamp = _now_id()
    users = int(os.environ.get("USERS", "200"))
    tokens = create_users(base, api_key, secret, token, users, stamp)
    print(f"ready users={len(tokens)} mock_ready={ready}", flush=True)

    results = []
    seq = 1
    seq_lock_note = []

    # --- concurrency until fail ---
    conc_levels = [1, 10, 25, 50, 100, 250, 500, 750, 1000, 1500, 2000, 3000]
    last_stable_conc = None
    cliff_conc = None
    for n in conc_levels:
        workers = min(n, 400)
        print(f"CONC start n={n} workers={workers}", flush=True)
        hits, wall = run_burst(
            base=base,
            tokens=tokens,
            stress_token=token,
            n=n,
            start_index=seq,
            wait=True,
            max_workers=workers,
        )
        seq += n
        s = summarize(n, "concurrency", hits, wall)
        results.append(asdict(s))
        print(
            f"CONC n={n} ok={s.ok_rate:.3f} done={s.completed}/{n} "
            f"fail={s.failed} p95={s.post_p95_ms:.0f} rps={s.recipes_per_sec:.1f} "
            f"err={s.errors} wall={s.wall_ms:.0f}",
            flush=True,
        )
        hard = s.ok_rate < 0.85 or s.failed > n * 0.1 or any(k.startswith("http_0") or k.startswith("http_5") for k in s.errors)
        if hard:
            cliff_conc = n
            print(f"CLIFF concurrency at n={n}", flush=True)
            break
        if s.ok_rate >= 0.95 and s.post_p95_ms < 20000:
            last_stable_conc = n
        time.sleep(2)

    # --- open-loop RPS until fail ---
    last_stable_rps = None
    cliff_rps = None
    rps = 20.0
    while rps <= 400:
        duration = 10.0
        total = max(1, int(rps * duration))
        interval = 1.0 / rps
        print(f"RPS start target={rps:g} total={total}", flush=True)
        wall0 = time.perf_counter()
        hits: list[Hit] = []
        with ThreadPoolExecutor(max_workers=min(500, max(32, int(rps * 3)))) as pool:
            futs = []
            for i in range(total):
                futs.append(
                    pool.submit(one_extract, base, tokens[i % len(tokens)], token, seq + i, wait=True)
                )
                time.sleep(interval)
            for fut in as_completed(futs):
                hits.append(fut.result())
        seq += total
        wall = (time.perf_counter() - wall0) * 1000
        s = summarize(rps, "rps", hits, wall)
        results.append(asdict(s))
        eff = s.recipes_per_sec / rps if rps else 0
        print(
            f"RPS target={rps:g} ok={s.ok_rate:.3f} done={s.completed}/{total} "
            f"p95={s.post_p95_ms:.0f} realized={s.recipes_per_sec:.1f} eff={eff:.2f} err={s.errors}",
            flush=True,
        )
        hard = (
            s.ok_rate < 0.85
            or s.failed > total * 0.1
            or any(k.startswith("http_0") or k.startswith("http_5") for k in s.errors)
            or s.post_p95_ms > 30000
            or eff < 0.35
        )
        if hard:
            cliff_rps = rps
            print(f"CLIFF rps at {rps:g}", flush=True)
            break
        last_stable_rps = rps
        if rps < 80:
            rps *= 1.5
        else:
            rps += 25
        time.sleep(3)

    # --- single giant burst ---
    burst_n = int(os.environ.get("BURST_N", "2000"))
    print(f"BURST start n={burst_n}", flush=True)
    hits, wall = run_burst(
        base=base,
        tokens=tokens,
        stress_token=token,
        n=burst_n,
        start_index=seq,
        wait=True,
        max_workers=min(500, burst_n),
    )
    seq += burst_n
    s = summarize(burst_n, "burst", hits, wall)
    results.append(asdict(s))
    print(
        f"BURST n={burst_n} ok={s.ok_rate:.3f} done={s.completed} p95={s.post_p95_ms:.0f} "
        f"rps={s.recipes_per_sec:.1f} err={s.errors}",
        flush=True,
    )

    # control probe
    control = one_extract(base, tokens[0], token, seq, wait=True)
    print(f"CONTROL status={control.status} final={control.final_status} ms={control.latency_ms:.0f}", flush=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ready": ready,
        "users": len(tokens),
        "last_stable_concurrency": last_stable_conc,
        "cliff_concurrency": cliff_conc,
        "last_stable_rps": last_stable_rps,
        "cliff_rps": cliff_rps,
        "control": asdict(control),
        "results": results,
        "notes": seq_lock_note,
    }
    (out / "max-report.json").write_text(json.dumps(report, indent=2))
    print(f"WROTE {out / 'max-report.json'}", flush=True)
    print(
        f"SUMMARY stable_conc={last_stable_conc} cliff_conc={cliff_conc} "
        f"stable_rps={last_stable_rps} cliff_rps={cliff_rps}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
