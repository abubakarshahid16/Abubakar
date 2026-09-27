"""Re-decide OCR routing (audit F6) for documents extracted under an older rule.

Pages extracted before OCR routing version 2 were sent to recognition only
when their text layer had fewer than 100 characters, and carry no recorded
reason (`pages.ocr_route_version` NULL). This re-opens each stored PDF and runs
`ocr.route_page` against the text ALREADY stored for every page. Nothing is
re-extracted, re-chunked or re-embedded by this script:

  * a page whose decision is unchanged only gets its reason and version;
  * a finished document with a page that NOW needs recognition is moved to
    `chunking`, and the running server's ingestion worker then reads only
    those pages (chunking is skipped as unchanged; the keyword index is
    rebuilt; only chunks whose text changed need new vectors).

DEFAULT IS AN ESTIMATE THAT WRITES NOTHING. On a live database the estimate
runs against `live_guard.diagnostic_copy()`, never the live file.

    python scripts/reroute_ocr.py --db backend/data/rag_intelligence.sqlite
    python scripts/reroute_ocr.py --db backend/data/rag_intelligence.sqlite --apply --live

`--apply --live` goes through `app.live_guard.prepare_live_write` (verified
backup + restore drill first), so STOP THE SERVER before running it, then
start it again with `python run.py` to let the worker do the recognition.

Prints ids and counts only, never page text or filenames.
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
    ap.add_argument("--apply", action="store_true",
                    help="write the new decisions (default: estimate only)")
    ap.add_argument("--live", action="store_true",
                    help="with --apply: write a live database, after the A5 backup "
                         "+ restore drill")
    ap.add_argument("--backup-dir", type=Path, default=None)
    ap.add_argument("--stale-only", action="store_true",
                    help="only documents with a page not decided by the current rule")
    args = ap.parse_args()
    target = args.db.resolve()

    from app import db, extract, live_guard, ocr  # noqa: E402
    from app.config import settings  # noqa: E402

    summary: dict = {"database": str(target), "applied": args.apply,
                     "route_version": ocr.OCR_ROUTE_VERSION}
    if args.apply and args.live:
        clearance = live_guard.prepare_live_write(
            target, reason="OCR routing v2 re-decision (pages.needs_ocr/ocr_route)",
            backup_dir=args.backup_dir)
        summary["rollback_point"] = clearance.backup_path
    elif live_guard.is_live_shaped(target):
        if args.apply:
            raise SystemExit("refusing: that is a live database; pass --live, which "
                             "takes a verified backup and runs a restore drill first")
        target = live_guard.diagnostic_copy(target)
        summary["estimated_on_copy"] = True
    settings.db_path = target
    db.reset_connection()
    db.init_db()  # additive: adds the routing columns if missing
    conn = db.connect()
    where = (" WHERE id IN (SELECT document_id FROM pages WHERE ocr_route_version IS NULL"
             " OR ocr_route_version != ?)" if args.stale_only else "")
    params = (ocr.OCR_ROUTE_VERSION,) if args.stale_only else ()
    docs = [r["id"] for r in conn.execute(
        f"SELECT id FROM documents{where} ORDER BY id", params)]

    totals: Counter = Counter()
    routes: Counter = Counter()
    requeued, missing, changed = [], [], []
    for doc_id in docs:
        r = extract.reroute_document(doc_id, apply=args.apply)
        if r["error"]:
            missing.append(doc_id)
            continue
        routes.update(r["routes"])
        for k in ("pages", "stale", "newly_needs_ocr", "no_longer_needs_ocr"):
            totals[k] += r[k]
        if r["newly_needs_ocr"]:
            changed.append({"document_id": doc_id, "newly_needs_ocr": r["newly_needs_ocr"]})
        if r["requeued"]:
            requeued.append(doc_id)
    summary.update({
        "documents": len(docs), **totals, "routes": dict(routes),
        # ~1.1 s/page on the audit's 2 vCPU box; a laptop measurement replaces it
        "estimated_ocr_seconds": round(totals["newly_needs_ocr"] * 1.1, 1),
        "documents_with_new_ocr_pages": changed,
        "documents_requeued" if args.apply else "documents_that_would_be_requeued": requeued,
        "documents_with_missing_file": missing,
    })
    db.reset_connection()
    live_guard.revoke_all()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
