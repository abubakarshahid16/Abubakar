"""Order 301.3 / certificate check 4: how are a standard's stored clause numbers written? Counts, on a COPY.

A standard numbers its own clauses in one style (ASME VIII Division 1: "UG-22", "UW-12", "1-1"; API and
ISO: "5.3.4.1"). A stored requirement whose clause is in a DIFFERENT style came from a heading number the
chunker took off the page layout (a numbered list, a page header), not from the standard's own numbering, and
a CRS row that cites it cites a clause that does not exist in the standard.

For each standard this prints how many active requirements carry no clause, a decimal clause ("7.16"), a
dashed clause ("UG-22", "A-1"), a number-dash-number clause ("1-1", for appendices), or anything else, and the
most common clause values of each style with their counts. Clause NUMBERS and counts only, never a sentence
(CLAUDE.md rule 1). Read-only, and on a COPY only (a live-shaped path is refused).

    python scripts/clause_numbering_report.py --db <copy.sqlite> [--document-id ID ...] [--top 8]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

#: Clause styles, most specific first. A clause is classified by its shape alone, never by a standard's name.
STYLES: tuple[tuple[str, re.Pattern], ...] = (
    ("decimal", re.compile(r"^\d+(?:\.\d+)+\.?$|^\d+\.$")),
    ("number_dash_number", re.compile(r"^\d+-\d+(?:\.\d+)*[A-Za-z]?$")),
    (
        "dashed",
        re.compile(r"^[A-Za-z]{1,5}-\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*[A-Za-z]?$"),
    ),
)


def style_of(clause: str | None) -> str:
    """The shape of one stored clause: none, decimal, number_dash_number, dashed or other."""
    text = (clause or "").strip()
    if not text:
        return "none"
    for name, pattern in STYLES:
        if pattern.match(text):
            return name
    return "other"


def report_document(conn: sqlite3.Connection, document_id: str, top: int = 8) -> dict:
    rows = [
        r[0]
        for r in conn.execute(
            "SELECT clause FROM standard_requirements WHERE standard_document_id = ?"
            " AND superseded_at IS NULL",
            (document_id,),
        )
    ]
    by_style: Counter = Counter()
    values: dict[str, Counter] = {}
    for clause in rows:
        style = style_of(clause)
        by_style[style] += 1
        if style != "none":
            values.setdefault(style, Counter())[clause.strip()] += 1
    return {
        "requirements": len(rows),
        "by_style": dict(sorted(by_style.items())),
        "distinct_clauses": {s: len(c) for s, c in sorted(values.items())},
        "most_common": {s: c.most_common(top) for s, c in sorted(values.items())},
    }


def main(argv: list[str] | None = None) -> int:
    from app import live_guard

    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", required=True, type=Path)
    p.add_argument("--document-id", action="append", default=[])
    p.add_argument("--top", type=int, default=8)
    args = p.parse_args(argv)
    path = args.db.resolve()
    if live_guard.is_live_shaped(path) or not path.exists():
        raise SystemExit(
            f"refusing: {path} is a live database or does not exist. Use a copy."
        )
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ids = args.document_id or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT standard_document_id FROM standard_requirements"
                " WHERE superseded_at IS NULL"
            )
        ]
        report = {i: report_document(conn, i, args.top) for i in sorted(ids)}
    finally:
        conn.close()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
