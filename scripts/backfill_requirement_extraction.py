"""Queue rule extraction for every COMPANY_STANDARD that never got it.

WHY THIS EXISTS (found 2026-09-28, real upload). Two hooks queue extraction:
`ingest._queue_extraction_if_standard` (role already COMPANY_STANDARD when
ingestion finishes) and `classification._queue_extraction_if_ready` (role set
afterwards, via `set_role` or `confirm`). Before this session, `confirm` -
the per-document "Details" form an administrator uses one document at a time -
had no such hook (`classification.py`, fixed alongside this script). Any
standard uploaded, indexed, and THEN classified through that form before the
fix stayed searchable with zero requirements extracted, forever, with nothing
on screen to say why.

This is the one-time catch-up for standards already stuck that way. Going
forward the code fix means new ones will not need it - this script exists for
the backlog, not as the permanent mechanism.

`enqueue_extraction` is idempotent per document, so running this twice, or
against a standard that is already queued or already has requirements, costs
nothing and changes nothing.

    python scripts/backfill_requirement_extraction.py                  # report only
    python scripts/backfill_requirement_extraction.py --apply          # queue them
    python scripts/backfill_requirement_extraction.py --apply --doc ID # one standard

REPORT (the default) reads a WAL-safe diagnostic copy and writes nothing. It
lists every COMPANY_STANDARD with zero requirements and no extraction job
already queued or running.

APPLY calls `standards.enqueue_extraction` against the LIVE database for each
one found - the same call the "Extract requirements" button makes, just for
every stuck standard at once instead of one click per document. It does not
write the database directly: it only inserts a job for the running server's
own worker to pick up, so the server must be running for the queued jobs to
actually drain (unlike the other `--apply` scripts here, this one wants the
server UP, not stopped - it is enqueueing work for it, not writing behind it).

Output carries document ids and filenames only, never document text.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _stuck_standards(conn: sqlite3.Connection, only: list[str] | None) -> list[dict]:
    from app.standards import COMPANY_STANDARD, EXTRACTION_STAGE

    rows = conn.execute(
        "SELECT d.id, d.filename, d.status FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id"
        " WHERE c.document_role = ? AND d.status = 'ready'"
        " ORDER BY d.filename", (COMPANY_STANDARD,)).fetchall()
    has_requirements = {r["standard_document_id"] for r in conn.execute(
        "SELECT DISTINCT standard_document_id FROM standard_requirements").fetchall()}
    has_job = {r["document_id"] for r in conn.execute(
        "SELECT DISTINCT document_id FROM jobs WHERE stage = ?"
        " AND state IN ('queued', 'running', 'retrying')", (EXTRACTION_STAGE,)).fetchall()}
    out = []
    for row in rows:
        if only and row["id"] not in only:
            continue
        if row["id"] in has_requirements or row["id"] in has_job:
            continue
        out.append({"document_id": row["id"], "filename": row["filename"]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path,
                    default=REPO / "backend" / "data" / "rag_intelligence.sqlite")
    ap.add_argument("--apply", action="store_true",
                    help="queue extraction on the running server's worker")
    ap.add_argument("--doc", action="append", help="limit to this standard's document id (repeatable)")
    args = ap.parse_args(argv)
    path = args.db.resolve()
    if not path.is_file():
        raise SystemExit(f"no database at {path}")

    from app import live_guard

    if not args.apply:
        copy = live_guard.diagnostic_copy(path) if live_guard.is_live_shaped(path) else path
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        stuck = _stuck_standards(conn, args.doc)
        print(json.dumps({"standards_needing_extraction": stuck}, indent=1))
        print(f"\n{len(stuck)} standard(s) have zero requirements and nothing queued. "
              "Run again with --apply (server should be running) to queue them.",
              file=sys.stderr)
        return 0

    if live_guard.is_live_shaped(path):
        clearance = live_guard.prepare_live_write(
            path, reason="backfill_requirement_extraction: queue stuck standards")
        print(f"rollback point: {clearance.backup_path}", file=sys.stderr)

    from app.config import settings
    settings.db_path = path
    from app import db, standards

    db.reset_connection()
    conn = db.connect()
    stuck = _stuck_standards(conn, args.doc)
    queued = []
    for std in stuck:
        job_id = standards.enqueue_extraction(std["document_id"])
        queued.append({**std, "job_id": job_id})
    print(json.dumps({"queued": queued}, indent=1))
    print(f"\nqueued {len(queued)}. The running server's worker will drain these; "
          "check the Standards Library page in a few minutes.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
