"""The CRS test bench (#1471): saved runs through the current decide + CRS code.

    python scripts/crs_bench.py --db <COPY of the database> [--out FILE]
                                [--baseline FILE.json] [--save FILE.json] [--stored-only]

READ-ONLY on the copy you pass: every replay runs on its own throw-away copy of
it, with every model and Claude call refused. Refuses the live database - take
a copy first (`live_guard.diagnostic_copy()`). The table holds counts, ids and
checklist field names only; the copy itself stays on this machine.

Exit codes: 0 green, 1 red (a wrong verdict, or a measure worse than
--baseline), 2 refused.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

from tools import crs_bench  # noqa: E402

from app import live_guard  # noqa: E402

LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"
TRUTH = REPO / "eval" / "bench" / "truth.json"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", required=True, help="a COPY of the database")
    ap.add_argument("--truth", default=str(TRUTH))
    ap.add_argument("--out", help="write the markdown table here (default: print it)")
    ap.add_argument("--baseline", help="a --save file to compare against (gate)")
    ap.add_argument("--save", help="save the numbers as JSON (a later --baseline)")
    ap.add_argument(
        "--stored-only",
        action="store_true",
        help="score the stored runs only; no replay",
    )
    ap.add_argument("--title", default="CRS bench")
    args = ap.parse_args(argv)
    db = Path(args.db).resolve()
    if db == LIVE.resolve() or live_guard.is_live_shaped(db):
        print(
            "refused: that is the live database. Copy it first "
            "(live_guard.diagnostic_copy()) and pass the copy."
        )
        return 2
    if not db.exists():
        print(f"refused: {db} does not exist")
        return 2
    truth = json.loads(Path(args.truth).read_text())
    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
    results = crs_bench.run_bench(db, truth, do_replay=not args.stored_only)
    text = crs_bench.render_markdown(
        results, truth, title=args.title, baseline=baseline
    )
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    if args.save:
        Path(args.save).write_text(json.dumps(results, indent=1, default=str))
    return 1 if crs_bench.gate(results, baseline) else 0


if __name__ == "__main__":
    raise SystemExit(main())
