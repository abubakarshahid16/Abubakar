"""How many stored clauses of one standard are in the standard's OWN numbering? (order 301.3) READ ONLY, counts only.

    python scripts/clause_shape_count.py --like ASME [--db PATH] [--own-pattern REGEX]

Takes a disposable copy of the database (`live_guard.diagnostic_copy`), picks the standard documents whose
filename or document number contains `--like`, and counts their current requirement rows by the SHAPE of the
stored clause: in the standard's own numbering (default pattern: a letter group, a hyphen, a number, as in the
paragraph numbers of a pressure-vessel code), a plain dotted number ("7.16"), no clause, or something else.
A plain dotted number on a standard that does not number that way is a clause the CRS would cite wrongly.

It prints counts per document id, never a clause or a sentence."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

#: The default "own numbering": letters, a hyphen, a number, and any (a)(1) suffix: "UG-125", "UW-12(b)".
OWN_DEFAULT = r"^[A-Z]{1,4}-\d+[A-Za-z]?(?:\s*\(\w+\))*$"
_DOTTED = re.compile(r"^\d+(?:\.\d+)+$")


def shape(clause: str | None, own: re.Pattern) -> str:
    text = " ".join(str(clause or "").split())
    if not text:
        return "no_clause"
    if own.match(text):
        return "own_numbering"
    if _DOTTED.match(text):
        return "plain_dotted_number"
    return "other"


def count(rows: list[tuple[str, str | None]], own_pattern: str = OWN_DEFAULT) -> dict:
    """`rows` are (document id, clause). Counts per document and in total, by shape."""
    own = re.compile(own_pattern)
    per: dict[str, Counter] = {}
    for doc, clause in rows:
        per.setdefault(doc, Counter())[shape(clause, own)] += 1
    total: Counter = Counter()
    for c in per.values():
        total.update(c)
    return {"documents": {d: dict(c) for d, c in per.items()}, "total": dict(total)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument("--like", required=True)
    parser.add_argument("--own-pattern", default=OWN_DEFAULT)
    args = parser.parse_args()
    from app import db, live_guard
    from app.config import settings

    settings.db_path = live_guard.diagnostic_copy(args.db or settings.db_path)
    db.reset_connection()
    like = f"%{args.like}%"
    rows = [
        (r["id"], r["clause"])
        for r in db.connect().execute(
            "SELECT r.standard_document_id AS id, r.clause AS clause FROM standard_requirements r"
            " JOIN documents d ON d.id = r.standard_document_id"
            " LEFT JOIN document_classification c ON c.document_id = d.id"
            " WHERE r.superseded_at IS NULL AND (d.filename LIKE ? OR c.document_number LIKE ?)",
            (like, like),
        )
    ]
    result = count(rows, args.own_pattern)
    for doc, c in sorted(result["documents"].items()):
        print(doc, dict(sorted(c.items())))
    print("total", dict(sorted(result["total"].items())), "rows:", len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
