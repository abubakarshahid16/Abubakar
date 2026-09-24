"""Reset one document so the worker re-extracts it from page 1.

    python scripts/resetdoc.py <doc_id> [--db PATH]

Deletes the document's `pages` rows and puts its `documents`/`jobs` rows back
to queued. A LIVE database only through `app.live_guard.prepare_live_write`:
a verified online backup and a restore drill first, refused otherwise (owner
decision 2026-09-25, after the B3 live-write incident). The default path is
the one the old version used, `data/rag_intelligence.sqlite` relative to the
current directory - the live file when run from `backend/`.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app import live_guard  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("doc_id")
    ap.add_argument("--db", type=Path, default=Path("data/rag_intelligence.sqlite"))
    args = ap.parse_args(argv)
    path = args.db.resolve()
    if not path.is_file():
        raise SystemExit(f"no database at {path}")
    if live_guard.is_live_shaped(path):
        clearance = live_guard.prepare_live_write(path, reason=f"resetdoc {args.doc_id}")
        print(f"rollback point: {clearance.backup_path}")
    c = sqlite3.connect(path)
    with c:
        c.execute("DELETE FROM pages WHERE document_id=?", (args.doc_id,))
        c.execute("UPDATE documents SET pages_done=0, needs_ocr_pages=0, page_count=NULL,"
                  " status='queued' WHERE id=?", (args.doc_id,))
        c.execute("UPDATE jobs SET state='running', stage='extract', pages_done=0,"
                  " last_completed_batch=NULL, pages_total=NULL WHERE document_id=?",
                  (args.doc_id,))
    c.close()
    print(f"reset {args.doc_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
