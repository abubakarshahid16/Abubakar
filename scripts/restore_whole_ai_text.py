"""Put back the whole AI text of stored lines that were cut before they were stored (order 14 W-C6; completeness rule 3).

Until this fix three writers shortened the AI reviewer's own words when a line was stored, with no mark. The run's own record
(`<data dir>/agent_reviews/<run>/trace.jsonl` and `steps/`) keeps what the AI sent, so the whole text is put back from it: no
model call, no cost. `app.ai_text_whole` finds the lines (the same check `crs_completeness` runs before every download).

A LIVE DATABASE GOES THROUGH `app.live_guard`: with `--live` the guard takes a verified backup and runs a restore drill first.
Without `--live`, a live database is refused.

    python scripts/restore_whole_ai_text.py --db <copy.sqlite> [run id ...]        (default: every run with stored lines)
    python scripts/restore_whole_ai_text.py --db backend/data/rag_intelligence.sqlite --live [run id ...]

The run folders are read from the database's own folder (`<db folder>/agent_reviews`). Prints ids and counts only, never text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument(
        "--live",
        action="store_true",
        help="write a live database, after the backup and restore drill",
    )
    ap.add_argument("--backup-dir", type=Path, default=None)
    ap.add_argument("runs", nargs="*")
    args = ap.parse_args(argv)
    target = args.db.resolve()

    from app import ai_text_whole, db, live_guard
    from app.config import settings

    summary: dict = {"database": str(target)}
    if args.live:
        clearance = live_guard.prepare_live_write(
            target,
            reason="order 14 W-C6: whole AI text put back from the run's record",
            backup_dir=args.backup_dir,
        )
        summary["rollback_point"] = clearance.backup_path
    elif live_guard.is_live_shaped(target):
        raise SystemExit(
            "refusing: that is a live database; pass --live, which takes a verified backup first"
        )
    settings.data_dir, settings.db_path = target.parent, target
    db.reset_connection()
    conn = db.connect()
    runs = args.runs or [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT run_id FROM agent_review_line ORDER BY run_id"
        )
    ]
    per_run = {}
    for run in runs:
        folder = target.parent / "agent_reviews" / run
        before = ai_text_whole.cuts_of_run(conn, run, folder)
        changed = ai_text_whole.restore(conn, run, folder)
        after = ai_text_whole.cuts_of_run(conn, run, folder)
        per_run[run] = {"record": before["checked"], "lines": before["lines"], "cut_before": len(before["cut"]),
                        "lines_restored": changed, "cut_after": len(after["cut"])}  # fmt: skip
    summary["runs"] = per_run
    summary["cut_before"] = sum(r["cut_before"] for r in per_run.values())
    summary["cut_after"] = sum(r["cut_after"] for r in per_run.values())
    db.reset_connection()
    live_guard.revoke_all()
    print(json.dumps(summary, indent=2))
    return 1 if summary["cut_after"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
