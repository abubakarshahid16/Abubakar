"""#1474: how many documents have each kind, and how many are `unknown`.

Counts only, read-only (the database is opened `mode=ro`; point it at a
diagnostic copy, never write the live file). The lead reads the unknown rate
daily; above 10% stops the cycle (#1474). The denominator is always printed.

Run: python scripts/document_kind_rate.py --db <copy.sqlite>
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app import document_kind

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    counts = document_kind.counts_from(conn)
    print(f"documents: {counts['total']}")
    for kind, n in sorted(counts["kinds"].items()):
        print(f"  {kind}: {n}")
    print(f"  unknown (kind empty, engineer asked): {counts['unknown']}")
    print(f"  no kind record yet: {counts['not_classified']}")
    rate = counts["unknown_rate"]
    print(
        "unknown rate: "
        + (
            "n/a"
            if rate is None
            else f"{counts['unknown']}/{counts['total']} = {rate:.1%}"
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
