"""Build the page ledger (master order B3, ADR-0025) for every existing document.

`page_ledger` rows are DERIVED - rebuilt from `pages`, `page_ocr`, `chunks`,
`exclusions` and `submittal_facts` by `page_ledger.refresh` - so this writes
nothing a later refresh or re-extraction cannot rebuild, and touches no other
table. Documents ingested before the ledger existed get `facts_recorded_by =
'derived'` with the parse reason stated as not recorded.

A LIVE DATABASE GOES THROUGH `app.live_guard`, never around it: with `--live`
the guard takes a verified online backup and runs a restore drill first, and
refuses the write if either fails. Without `--live`, a live database is
refused by `db.connect()` itself. (The first version of this script checked
the path on its own, from its own location, and run from a git worktree it
wrote to the main checkout's live file - 2026-09-24, B3 checkpoint 16.14.)

    python scripts/backfill_page_ledger.py --db <copy.sqlite>
    python scripts/backfill_page_ledger.py --db backend/data/rag_intelligence.sqlite --live

Prints ids and counts only, never page text.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--live", action="store_true",
                    help="write a live database, after the A5 backup + restore drill")
    ap.add_argument("--backup-dir", type=Path, default=None,
                    help="where the A5 backup goes (default <checkout>-backups); "
                         "if no verified backup can be taken there, nothing is written")
    args = ap.parse_args()
    target = args.db.resolve()

    from app import db, live_guard, page_ledger  # noqa: E402
    from app.config import settings  # noqa: E402

    summary: dict = {"database": str(target)}
    if args.live:
        clearance = live_guard.prepare_live_write(
            target, reason="B3 page-ledger backfill (derived rows only)",
            backup_dir=args.backup_dir)
        summary["rollback_point"] = clearance.backup_path
    elif live_guard.is_live_shaped(target):
        raise SystemExit("refusing: that is a live database; pass --live, which "
                         "takes a verified backup and runs a restore drill first")
    settings.db_path = target
    db.reset_connection()
    db.init_db()  # additive: creates page_ledger if missing
    conn = db.connect()
    docs = [r["id"] for r in conn.execute("SELECT id FROM documents ORDER BY id")]
    rows = 0
    for doc in docs:
        rows += page_ledger.refresh(doc)
    summary.update({"documents": len(docs), "ledger_rows": rows})
    for column in ("native_status", "ocr_status", "index_status", "facts_status"):
        summary[column] = dict(Counter(
            r[0] for r in conn.execute(f"SELECT {column} FROM page_ledger")))
    db.reset_connection()
    live_guard.revoke_all()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
