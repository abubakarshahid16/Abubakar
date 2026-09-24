"""Backfill document_number/revision for every COMPANY_STANDARD from its own
cover pages (owner order, 2026-09-24, standards-inventory stage 1).

Calls `app.standards_inventory.backfill_cover_metadata` per standard, which
NEVER overwrites an already-set document_number/revision (human-confirmed or
set by an earlier run) and NEVER guesses - a cover page with nothing
recognisable leaves the field NULL, reported here as unresolved rather than
silently skipped.

A LIVE DATABASE GOES THROUGH `app.live_guard`, never around it: with `--live`
the guard takes a verified online backup and runs a restore drill first, and
refuses the write if either fails. Without `--live`, a live database is
refused by `db.connect()` itself.

    python scripts/backfill_standard_metadata.py --db <copy.sqlite>
    python scripts/backfill_standard_metadata.py --db backend/data/rag_intelligence.sqlite --live

Prints ids, page numbers and short quotes only - the quotes are a document
number or revision code, never a paragraph of document text.
"""
from __future__ import annotations

import argparse
import json
import sys
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

    from app import db, live_guard, standards, standards_inventory  # noqa: E402
    from app.config import settings  # noqa: E402

    summary: dict = {"database": str(target)}
    if args.live:
        clearance = live_guard.prepare_live_write(
            target, reason="B5 standards-inventory cover-page backfill",
            backup_dir=args.backup_dir)
        summary["rollback_point"] = clearance.backup_path
    elif live_guard.is_live_shaped(target):
        raise SystemExit("refusing: that is a live database; pass --live, which "
                         "takes a verified backup and runs a restore drill first")
    settings.db_path = target
    db.reset_connection()
    db.init_db()
    standards_inventory.ensure_schema()
    conn = db.connect()
    doc_ids = [r["id"] for r in conn.execute(
        "SELECT d.id FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id"
        " WHERE c.document_role = ?", (standards.COMPANY_STANDARD,))]

    results = [standards_inventory.backfill_cover_metadata(doc_id)
              for doc_id in doc_ids]
    changed = [r for r in results if r.get("changed")]
    unattempted = [r for r in results if not r.get("attempted")]
    no_evidence = [r for r in results
                   if r.get("attempted") and not r.get("changed")]

    summary.update({
        "standards": len(doc_ids),
        "changed": len(changed),
        "no_cover_evidence": len(no_evidence),
        "unattempted": len(unattempted),
        "changes": [{k: v for k, v in r.items() if k != "reason"}
                   for r in changed],
    })
    db.reset_connection()
    live_guard.revoke_all()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
