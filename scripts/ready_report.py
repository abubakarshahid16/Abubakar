"""What "ready" would say for documents already in a database, written to a COPY only.

    python scripts/ready_report.py --db <a copy of the database> [--doc ID ...]

An existing document's ledger and decision are written when the server next finishes or
re-reads it; nothing back-fills the live database. This script answers the question ahead
of that: it refuses a live-shaped path, refreshes the ledger on the copy it is given, and
decides with `reading_state`. It re-reads no file's text and calls no model. A Word file read
before WORD_PAGE_MARKERS_ENABLED has no picture answers, so it shows as unaccounted here until
it is re-read. Prints ids and counts only, never document text.
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
    ap.add_argument(
        "--db", required=True, type=Path, help="a COPY of the database; it is written"
    )
    ap.add_argument(
        "--doc",
        action="append",
        default=None,
        help="document id (repeatable); default all",
    )
    args = ap.parse_args()

    from app import db, live_guard, page_ledger, reading_state
    from app.config import settings

    if live_guard.is_live_shaped(args.db):
        raise SystemExit("REFUSED: this is a live database; give a copy")
    settings.db_path = args.db
    settings.one_checked_definition_enabled = True
    db.reset_connection()
    db.init_db(args.db)
    conn = db.connect()
    ids = args.doc or [
        r[0] for r in conn.execute("SELECT id FROM documents ORDER BY id")
    ]
    out = {}
    for doc_id in ids:
        page_ledger.refresh(doc_id)
        out[doc_id] = reading_state.report(doc_id)
    db.reset_connection()
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
