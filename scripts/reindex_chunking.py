"""Re-extract and re-chunk documents whose chunks are STALE for this chunker.

WHY THIS EXISTS (chunking-quality, 2026-09-27). `chunker.CHUNKER_VERSION` 5
and the table reader in `extract.py` change how every document is chunked:
ruled tables become table chunks, data-sheet rows stop being dropped, clause
labels survive numbering gaps. A document's chunks are rebuilt only when
`chunk_document` runs for it, and nothing re-runs it for a document that is
already READY. This script finds the stale ones and rebuilds them.

Version 6 (2026-09-29): a heading with nothing under it, and the heading lines
of a contents page, are kept in chunk text instead of nowhere. Same script.
Version 7 (2026-09-29): a table read as all header, and a note inside a table's
border in no cell, are kept too. Same script.

WHAT "STALE" MEANS: `documents.chunk_signature` differs from the signature the
current chunker computes (`chunker.is_stale`) - an older CHUNKER_VERSION, or
different extracted text/tables. After the version bump, every document chunked
before it is stale.

    python scripts/reindex_chunking.py                    # report only
    python scripts/reindex_chunking.py --apply            # rebuild the stale ones
    python scripts/reindex_chunking.py --apply --doc ID   # one document

REPORT (the default) reads a WAL-safe diagnostic copy of the database and
writes nothing. It prints, per stale document, how many requirement rows a
re-chunk would delete (chunks cascade into `standard_requirements`) and how
many review findings cite them.

APPLY writes the database, so:
  * STOP THE SERVER FIRST. Only one process may write the live database.
  * A live database is cleared through `live_guard.prepare_live_write`: a
    verified backup and a restore drill before anything is written. The
    backup path is printed - it is the rollback point.
  * Per stale document: re-extract every page (text is rewritten identically;
    the new `pages.tables_json` is filled; recognised OCR text lives in
    `page_ocr` and is untouched), then `chunk_document(force=True)`.
  * A document whose re-chunk would orphan review findings, or delete a
    CONFIRMED requirement, is SKIPPED unless --acknowledge-orphaned-findings
    is given (B38: the refusal is recorded in `audit_events` either way).
  * Each rebuilt document is left at `indexing_keyword`. Start the server
    (`python run.py`): its worker rebuilds the keyword index and the vectors,
    marks the document READY, and re-queues requirement extraction for
    standards. Chunk ids change, so every chunk is re-embedded.

Output carries document ids, filenames and counts only - never document text.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _survey(conn: sqlite3.Connection, only: list[str] | None) -> list[dict]:
    from app import chunker

    rows = conn.execute("SELECT id, filename, status FROM documents ORDER BY filename").fetchall()
    out = []
    for row in rows:
        if only and row["id"] not in only:
            continue
        if not chunker.is_stale(conn, row["id"]):
            continue
        try:
            reqs = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(confirmed_by IS NOT NULL), 0) AS c"
                " FROM standard_requirements WHERE chunk_id IN"
                " (SELECT id FROM chunks WHERE document_id = ?)", (row["id"],)).fetchone()
            cited = conn.execute(
                "SELECT COUNT(*) FROM review_findings WHERE requirement_id IN"
                " (SELECT id FROM standard_requirements WHERE chunk_id IN"
                "  (SELECT id FROM chunks WHERE document_id = ?))", (row["id"],)).fetchone()[0]
        except sqlite3.OperationalError:
            reqs, cited = {"n": 0, "c": 0}, 0
        out.append({"document_id": row["id"], "filename": row["filename"],
                    "status": row["status"], "requirements_deleted_by_rechunk": reqs["n"],
                    "confirmed_requirements": reqs["c"], "findings_citing_them": cited})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path,
                    default=REPO / "backend" / "data" / "rag_intelligence.sqlite")
    ap.add_argument("--apply", action="store_true", help="rebuild (server must be stopped)")
    ap.add_argument("--doc", action="append", help="limit to this document id (repeatable)")
    ap.add_argument("--acknowledge-orphaned-findings", action="store_true",
                    help="also rebuild documents whose requirements review findings cite")
    args = ap.parse_args(argv)
    path = args.db.resolve()
    if not path.is_file():
        raise SystemExit(f"no database at {path}")

    from app import live_guard
    from app.config import settings

    if not args.apply:
        copy = live_guard.diagnostic_copy(path) if live_guard.is_live_shaped(path) else path
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        stale = _survey(conn, args.doc)
        total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        print(json.dumps({"documents": total, "stale": len(stale), "stale_documents": stale},
                         indent=1))
        print(f"\n{len(stale)} of {total} documents are stale. "
              "Stop the server, then run again with --apply.", file=sys.stderr)
        return 0

    settings.db_path = path
    if live_guard.is_live_shaped(path):
        clearance = live_guard.prepare_live_write(path, reason="reindex_chunking: chunker v5")
        print(f"rollback point: {clearance.backup_path}", file=sys.stderr)
    from app import chunker, db, extract, orphan_guard

    db.reset_connection()
    db.init_db(path)  # additive: adds any missing schema/columns (e.g. pages.ocr_route
                       # from fix/ocr-trigger-per-page) before this script writes to them.
                       # Without this, a live DB that has never had the server started
                       # against the merged schema crashes on the first write with
                       # "table pages has no column named ocr_route" - reindex_chunking
                       # must not depend on run order against other scripts or the server.
    conn = db.connect()
    stale = _survey(conn, args.doc)
    done, skipped = [], []
    for doc in stale:
        doc_id = doc["document_id"]
        risky = doc["findings_citing_them"] or doc["confirmed_requirements"]
        if risky and not args.acknowledge_orphaned_findings:
            skipped.append({**doc, "reason": "re-chunk would orphan findings or delete "
                                              "confirmed requirements"})
            continue
        with conn:
            conn.execute(
                "UPDATE jobs SET last_completed_batch = NULL, state = 'running',"
                " stage = 'extract' WHERE id = (SELECT id FROM jobs WHERE document_id = ?"
                " ORDER BY started_at DESC LIMIT 1)", (doc_id,))
        try:
            extract.extract_document(doc_id)
            result = chunker.chunk_document(
                doc_id, force=True,
                acknowledge_orphaned_findings=args.acknowledge_orphaned_findings)
        except orphan_guard.OrphaningRefused as exc:  # pragma: no cover - guarded above
            skipped.append({**doc, "reason": str(exc)})
            continue
        done.append({"document_id": doc_id, "filename": doc["filename"],
                     "chunks": result.get("chunks"),
                     "retrievable": result.get("chunks_retrievable"),
                     "table_chunks": result.get("tables_kept_whole")})
    print(json.dumps({"rebuilt": done, "skipped": skipped}, indent=1))
    print(f"\nrebuilt {len(done)}, skipped {len(skipped)}. Start the server "
          "(python run.py) to rebuild the keyword index and vectors.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
