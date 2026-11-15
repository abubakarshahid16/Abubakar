#!/usr/bin/env python
"""READ-ONLY preview of what the "maximum/minimum <subject> shall be <value> <unit>" reading changes in the stored standards rows (counts per book, ids only).

    python scripts/subject_limit_preview.py --db <COPY of the database> [--json out.json] [--ids ids.txt]

Opens the database read-only (`mode=ro`, immutable) and refuses the live-shaped path. For every `standard_requirements` row it re-reads the stored sentence with the
extractor's own `requirements_3b.parse_limit`:
  * a `statement` row that now carries a limit (operator, value, unit): GAINS a number rule (the rows a re-extraction would change; counted per standard book);
  * a row that already carries a limit and is read DIFFERENTLY now (operator, value or unit): CHANGED (must be 0: the new shape is tried only where nothing else read the sentence);
  * every other row: unchanged.
Writes no row. The re-extraction itself is `scripts/rehearse_requirement_reextraction.py` (the lead rehearses it on a copy and runs it with a backup)."""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--json")
    ap.add_argument(
        "--without-shape",
        action="store_true",
        help="read the sentences WITHOUT the new shape (the baseline of what the old parser read)",
    )
    ap.add_argument(
        "--ids", help="write the ids of the rows that gain a limit, one per line"
    )
    args = ap.parse_args()
    from app import live_guard, own_value_limit, requirements_3b as r3b

    if args.without_shape:
        own_value_limit.subject_be = lambda sentence: None  # type: ignore[assignment]

    if live_guard.is_live_shaped(Path(args.db)):
        print("refused: a live-shaped path; make a copy first")
        return 2
    conn = sqlite3.connect(
        f"file:{Path(args.db).resolve()}?mode=ro&immutable=1", uri=True
    )
    gained: collections.Counter = collections.Counter()
    changed, total, numeric = [], 0, 0
    gained_ids: list[str] = []
    for rid, doc, text, rtype, op, val, unit in conn.execute(
        "SELECT id, standard_document_id, requirement_text, requirement_type, operator, value, unit FROM standard_requirements"
    ):
        total += 1
        if not text or rtype not in ("statement", "numeric_limit"):
            continue
        lim = r3b.parse_limit(text)
        if rtype == "statement":
            if (
                lim is not None
                and lim.get("operator")
                and lim.get("value") is not None
                and lim.get("unit")
            ):
                gained[doc] += 1
                gained_ids.append(rid)
        else:
            numeric += 1
            if lim is None or (
                lim.get("operator"),
                lim.get("value"),
                lim.get("unit"),
            ) != (op, val, unit):
                changed.append(
                    rid
                )  # also rows the stored reading came from a table or another reader: reported, not judged here
    out = {
        "rows": total,
        "numeric_rows_checked": numeric,
        "statement_rows_that_gain_a_limit": sum(gained.values()),
        "books_with_gains": len(gained),
        "per_book": dict(gained.most_common()),
        "numeric_rows_read_differently_by_the_sentence_parser": len(changed),
    }
    print(json.dumps({k: v for k, v in out.items() if k != "per_book"}, indent=1))
    print("per book (document id: rows gained):", dict(list(gained.most_common(15))))
    if args.json:
        Path(args.json).write_text(
            json.dumps({**out, "changed_ids": changed}, indent=1)
        )
    if args.ids:
        Path(args.ids).write_text("\n".join(gained_ids) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
