"""The review X-ray (order 219): one local HTML page of everything a review stored.

    python scripts/review_xray.py --run <review_run_id> --db <copy of the database>

READ-ONLY: it opens the database `mode=ro`, makes no AI call and no network
call, and refuses the live database (`backend/data/rag_intelligence.sqlite`):
take a copy first (`live_guard.diagnostic_copy()`, or copy all three files
.sqlite / -wal / -shm). It writes `backend/data/debug/xray-<run>.html`
(git-ignored); the page holds document values, so it stays on this machine.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from app import live_guard  # noqa: E402
from tools import review_xray  # noqa: E402

LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--run", required=True, help="the review run id")
    ap.add_argument("--db", required=True, help="a COPY of the database")
    ap.add_argument(
        "--out", help="output file (default backend/data/debug/xray-<run>.html)"
    )
    args = ap.parse_args(argv)
    db = Path(args.db).resolve()
    if db == LIVE.resolve() or live_guard.is_live_shaped(db):
        print(
            "refused: that is the live database. Copy it first (live_guard.diagnostic_copy()) and pass the copy."
        )
        return 2
    if not db.exists():
        print(f"refused: {db} does not exist")
        return 2
    try:
        report = review_xray.build(db, args.run)
    except LookupError as exc:
        print(f"refused: {exc}")
        return 1
    out = (
        Path(args.out)
        if args.out
        else REPO / "backend" / "data" / "debug" / f"xray-{args.run}.html"
    ).resolve()
    if out.is_relative_to(REPO) and not out.is_relative_to(REPO / "backend" / "data"):
        print(
            "refused: the page holds document text; write it outside the repo or under backend/data/ (git-ignored)."
        )
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(review_xray.render_html(report), encoding="utf-8")
    print(
        f"wrote {out} ({sum(len(s['rows']) for s in report['sections'])} rows in {len(report['sections'])} sections)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
