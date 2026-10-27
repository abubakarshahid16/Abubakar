"""Counts-only diagnosis of one run's internal CRS (order 236). READ ONLY.

    python scripts/crs_row_diagnosis.py RUN_ID [--db backend/data/rag_intelligence.sqlite]

Takes a verified disposable copy of the database (`live_guard.diagnostic_copy`;
the live file is opened read-only), composes the sheet as the preview and the
export do, and prints counts. No document text, no file names.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id")
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    from tools import crs_row_diagnosis

    from app import access, db, live_guard
    from app.config import settings

    copy = live_guard.diagnostic_copy(args.db or settings.db_path)
    settings.db_path = copy
    db.reset_connection()
    ids = frozenset(r["id"] for r in db.connect().execute("SELECT id FROM documents"))
    scope = access.AccessScope(user_id="diagnosis", allowed_document_ids=ids)
    print(json.dumps(crs_row_diagnosis.diagnose(args.run_id, scope), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
