"""#1474: how many documents have each kind, and how many are `unknown`.

Counts only, read-only (the database is opened `mode=ro`; point it at a
diagnostic copy, never write the live file). Two numbers, each with its own
boundary: unknown of the documents that HAVE a kind decision (the rate the 10%
stop rule of #1474 means), and how many documents are decided at all.

`--decide-all` first runs the decider over every document on a THROW-AWAY copy
of the database (the file given is only read), so the rate covers the whole
library without writing the live DB.

Run: python scripts/document_kind_rate.py --db <copy.sqlite> [--decide-all]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _decide_all_on_copy(source: Path):
    """Counts after the decider ran over every document of a temporary copy."""
    from app import classification, db, document_kind
    from app.config import settings

    with tempfile.TemporaryDirectory(prefix="kind-rate-") as tmp:
        target = Path(tmp) / "copy.sqlite"
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(source) + suffix)
            if src.exists():
                shutil.copy2(src, str(target) + suffix)
        old = (settings.db_path, settings.data_dir, settings.document_kind_enabled)
        settings.db_path, settings.data_dir = target, Path(tmp)
        settings.document_kind_enabled = True
        db.reset_connection()
        try:
            conn = db.connect()
            for row in conn.execute("SELECT id FROM documents").fetchall():
                classification.classify_document_kind(row["id"])
            return document_kind.counts_from(conn)
        finally:
            db.reset_connection()
            settings.db_path, settings.data_dir, settings.document_kind_enabled = old


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--decide-all", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app import document_kind

    if args.decide_all:
        counts = _decide_all_on_copy(Path(args.db))
        print("(decider run over every document on a throw-away copy)")
    else:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        counts = document_kind.counts_from(conn)
    print("\n".join(document_kind.rate_lines(counts)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
