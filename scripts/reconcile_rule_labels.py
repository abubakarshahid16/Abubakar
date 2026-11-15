"""Reconcile the labels two readers differ on only in a word code can reconcile (comparator "required" against "statement",
or strength only), for a rule with no number and no negation. Code only: no model, no request.

    python scripts/reconcile_rule_labels.py --db <copy.sqlite> --lab <lab copy.sqlite>            dry run: counts and ids
    python scripts/reconcile_rule_labels.py --db <copy.sqlite> --lab <lab copy.sqlite> --apply    write on the COPY
    python scripts/reconcile_rule_labels.py --db <copy.sqlite> --undo                             put the reconciled labels back
    python scripts/reconcile_rule_labels.py --db backend/data/rag_intelligence.sqlite --lab <lab> --apply --live

A live-shaped database is refused unless `--live` is given, and `--live` goes through `app.live_guard.prepare_live_write` (verified
backup, integrity check, restore drill) first. The lab copy is opened read-only. Prints counts and ids, never a quote.
See `app/rule_label_reconcile.py` for what is reconciled, why it is safe and how it is undone.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument(
        "--lab",
        type=Path,
        help="the lab copy that holds the two readers' answers (read only)",
    )
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--backup-dir", type=Path, default=None)
    args = ap.parse_args(argv)
    target = args.db.resolve()
    if not args.undo and args.lab is None:
        print("REFUSED: --lab is needed (the lab copy holds the readers' answers)")
        return 2

    from app import live_guard, rule_label_reconcile as R

    summary: dict = {"database": target.name}
    writing = args.apply or args.undo
    if live_guard.is_live_shaped(target):
        if not args.live:
            print(
                "REFUSED: that is a live database; pass --live (it will make a verified backup first)"
            )
            return 2
        if writing:
            clearance = live_guard.prepare_live_write(
                target,
                reason="reconcile rule labels (code_reconciled)",
                backup_dir=args.backup_dir,
            )
            summary["rollback_point"] = clearance.backup_path
    elif args.live:
        print("REFUSED: --live names a database that is not live-shaped")
        return 2
    conn = sqlite3.connect(
        str(target) if writing else f"file:{target}?mode=ro",
        uri=not writing,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    try:
        if args.undo:
            summary["put_back"] = R.undo(conn)
        else:
            plans, held = R.plan_all(conn, _open_ro(args.lab))
            summary["would_reconcile"] = len(plans)
            summary["by_reason"] = dict(Counter(p.reason for p in plans))
            summary["held"] = dict(held)
            if args.apply:
                summary["reconciled"] = R.apply(conn, plans)
    finally:
        conn.close()
        live_guard.revoke_all()
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
