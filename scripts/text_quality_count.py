"""How many stored requirements would the text-quality gate flag? (#618) READ ONLY, counts only.

    python scripts/text_quality_count.py [--db PATH]

Takes a disposable copy of the database (`live_guard.diagnostic_copy`), reads every current
requirement sentence and counts: how many the gate flags now; how many it would flag WITHOUT the
dictionary-share rule (the short-list rule only); so the share the new rule adds is visible before
it is trusted. It prints counts, never a sentence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    from app import db, live_guard
    from app import requirement_quality as rq
    from app.config import settings

    settings.db_path = live_guard.diagnostic_copy(args.db or settings.db_path)
    db.reset_connection()
    rows = (
        db.connect()
        .execute(
            "SELECT COALESCE(source_text, requirement_text) AS t FROM standard_requirements"
            " WHERE superseded_at IS NULL"
        )
        .fetchall()
    )
    now = sum(1 for r in rows if rq.text_quality(r["t"]))
    keep = rq._UNKNOWN_SHARE
    rq._UNKNOWN_SHARE = (
        2.0  # the dictionary-share rule off: what the other rules alone flag
    )
    without = sum(1 for r in rows if rq.text_quality(r["t"]))
    rq._UNKNOWN_SHARE = keep
    print(f"requirements read: {len(rows)}")
    print(f"flagged now: {now}   flagged without the dictionary-share rule: {without}")
    print(f"added by the dictionary-share rule: {now - without}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
