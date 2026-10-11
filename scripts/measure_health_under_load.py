"""Measure `/api/health` while the backend's background jobs run (#626), on a COPY.

The owner saw `/api/health` take 7 to 9 s on an idle app. Health itself does
almost nothing, so the suspicion is the background work in the same process:
the risk-detection scan (`risks.run_detection`) and the acronym rebuild
(`acronyms.warm_all`). This runs the app IN THIS PROCESS against a database
copy, starts one job at a time in a thread, and calls `/api/health` every
`--every` seconds until the job ends. The same interpreter, the same GIL and
the same thread pool as the server - which is the point.

Reports, per phase (idle, risk detection, acronym rebuild): calls, median,
95th percentile and slowest health time, and how long the job ran. Timings and
counts only. A live-shaped database path is refused; no model is called.

    python scripts/measure_health_under_load.py --db <copy.sqlite> --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def summarise(seconds: list[float]) -> dict:
    """Calls, median, 95th percentile and slowest, in seconds. Pure."""
    if not seconds:
        return {"calls": 0}
    ordered = sorted(seconds)
    p95 = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"calls": len(ordered), "median_s": round(statistics.median(ordered), 4),
            "p95_s": round(p95, 4), "max_s": round(ordered[-1], 4)}


def probe_while(client, job, *, every: float) -> dict:
    """Run `job` in a thread; time `/api/health` every `every` seconds until it
    ends (at least once). A non-200 is counted, never timed as a success."""
    done = threading.Event()
    failed: list[str] = []

    def run() -> None:
        try:
            job()
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            failed.append(type(exc).__name__)
        finally:
            done.set()

    started = time.perf_counter()
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    times: list[float] = []
    errors = 0
    while True:
        t = time.perf_counter()
        status = client.get("/api/health").status_code
        if status == 200:
            times.append(time.perf_counter() - t)
        else:
            errors += 1
        if done.wait(every):
            break
    worker.join()
    return {**summarise(times), "non_200": errors, "job_seconds": round(time.perf_counter() - started, 1),
            "job_error": failed[0] if failed else None}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--every", type=float, default=0.2, help="seconds between health calls")
    ap.add_argument("--idle-calls", type=int, default=30)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    path = args.db.resolve()
    # The environment BEFORE any app import: settings are read once, at import.
    data = path.parent / "s1_data"
    os.environ.update({"DB_PATH": str(path), "DATA_DIR": str(data), "AUTH_MODE": "disabled",
                       "STARTUP_WARMUP": "false"})
    from app import live_guard
    if live_guard.is_live_shaped(path):
        raise SystemExit(f"refusing: {path} is a live database path. Measure on a copy.")
    data.mkdir(exist_ok=True)
    from fastapi.testclient import TestClient

    from app import acronyms, db, risks
    from app.config import settings
    from app.main import app
    assert Path(settings.db_path).resolve() == path, "the app is not on the copy"

    report: dict = {"database": path.name, "every_s": args.every,
                    "review_findings": db.connect().execute(
                        "SELECT count(*) FROM review_findings").fetchone()[0]}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        idle = []
        for _ in range(args.idle_calls):
            t = time.perf_counter()
            assert client.get("/api/health").status_code == 200
            idle.append(time.perf_counter() - t)
            time.sleep(args.every)
        report["idle"] = summarise(idle)
        report["risk_detection"] = probe_while(client, risks.run_detection, every=args.every)
        report["acronym_rebuild"] = probe_while(client, acronyms.warm_all, every=args.every)
    print(json.dumps(report, indent=1))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
