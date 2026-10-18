"""Order 109: where the review list (`GET /api/reviews/runs`) spends its time.

Run on the PC against the live database; it never opens the live file for
writing. It makes a WAL-safe diagnostic copy (`live_guard.diagnostic_copy`),
builds every run's summary the way the list route does, and prints how long
each step took in total, how many times it ran, and its share of the whole.

Prints step names, counts and seconds only: no filename, no document text,
no finding text (CLAUDE.md rule 1).

    python scripts/profile_run_list.py              # the configured database
    python scripts/profile_run_list.py --db PATH    # another database file
    python scripts/profile_run_list.py --repeat 3   # best of three
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("HEAVY_JOB_LOCK", "off")

#: (module attribute path, label): the steps `main._run_summary` calls per run.
STEPS = (
    ("app.submittal_review.get_review_run", "get_review_run"),
    ("app.comparison.run_outcome", "comparison.run_outcome"),
    ("app.comparison.plain_outcome", "comparison.plain_outcome"),
    ("app.comparison.review_codes", "comparison.review_codes"),
    ("app.review_jobs.job_for_run", "review_jobs.job_for_run"),
    ("app.ai_engineering_check.ai_check_status", "ai_check_status"),
    ("app.crs_issue.last_issued_at", "crs_issue.last_issued_at"),
    ("app.crs_wording.summary_of", "crs_wording.summary_of"),
    ("app.ai_numbers.for_run", "ai_numbers.for_run"),
    ("app.main._standards_change", "main._standards_change"),
)


def _timed(totals: dict, label: str, fn):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        try:
            return fn(*args, **kwargs)
        finally:
            totals[label][0] += 1
            totals[label][1] += time.perf_counter() - start

    return wrapper


def _patch(totals: dict) -> None:
    import importlib

    for path, label in STEPS:
        module_name, attr = path.rsplit(".", 1)
        module = importlib.import_module(module_name)
        setattr(module, attr, _timed(totals, label, getattr(module, attr)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", help="database file (default: the configured one)")
    parser.add_argument(
        "--repeat", type=int, default=1, help="runs; the fastest is kept"
    )
    args = parser.parse_args()

    from app import access, db, live_guard
    from app.config import settings

    source = Path(args.db) if args.db else Path(settings.db_path)
    copy = live_guard.diagnostic_copy(source)
    settings.db_path = copy
    db.reset_connection()

    from app import main as main_mod
    from app import submittal_review

    documents = frozenset(
        r["id"] for r in db.connect().execute("SELECT id FROM documents")
    )
    scope = access.AccessScope(user_id=None, allowed_document_ids=documents)
    totals: dict = defaultdict(lambda: [0, 0.0])
    _patch(totals)
    best = None
    for _ in range(max(1, args.repeat)):
        totals.clear()
        start = time.perf_counter()
        runs = submittal_review.list_review_runs(allowed_document_ids=documents)
        listed = time.perf_counter() - start
        body = [main_mod._run_summary(run, scope) for run in runs]
        wall = time.perf_counter() - start
        size = len(json.dumps({"runs": body}, default=str))
        if best is None or wall < best[0]:
            best = (
                wall,
                listed,
                len(runs),
                size,
                {k: list(v) for k, v in totals.items()},
            )
    wall, listed, count, size, totals = best
    print(f"runs: {count}   documents readable: {len(documents)}")
    print(f"whole list: {wall:.2f} s   response: {size / 1024:.0f} KB")
    print(f"  list_review_runs query: {listed:.2f} s")
    print(f"{'step':32} {'calls':>6} {'seconds':>8} {'share':>6}")
    for label, (calls, seconds) in sorted(totals.items(), key=lambda kv: -kv[1][1]):
        print(f"{label:32} {calls:6d} {seconds:8.2f} {seconds / wall:6.0%}")
    print("(steps nest: run_outcome includes a get_review_run, so shares overlap)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
