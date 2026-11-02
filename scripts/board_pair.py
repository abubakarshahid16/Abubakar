"""The board's call for risk and coverage (plan change 6 part B). The board is the
planner's page outside this repo, so this is the one way it asks: the same
`coverage_pair.for_run` the bench and the CRS use, on a COPY, read only.

    python scripts/board_pair.py --db <COPY of the database> --run <run id> [--run ...] [--json]

Refuses the live database. Exit codes: 0 done, 1 no such run, 2 refused.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--run", required=True, action="append")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    from app import coverage_pair, live_guard

    if live_guard.is_live_shaped(args.db):
        print(
            "the board call never opens the live database; pass a copy", file=sys.stderr
        )
        return 2
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        pairs = [
            coverage_pair.public_view(coverage_pair.for_run(conn, run))
            for run in args.run
        ]
    finally:
        conn.close()
    if any(p is None for p in pairs):
        print("no such review run in this copy", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(pairs))
        return 0
    for p in pairs:
        print(f"{p['run'][:8]}: {p['line']} {p['checklist_line']}")
        print(f"  {p['boundary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
