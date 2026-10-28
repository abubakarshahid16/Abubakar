"""Order 291.1 point 4: is each standard's rule list organised? COUNTS ONLY, read-only, on a COPY.

Per standard (by document id): the rules held (not superseded), by type; rules with and without a
clause number; rules with and without a page; duplicate rules (the same sentence, whitespace and case
folded, held more than once in one standard: the extra rows); and rules whose clause number goes
backward while the page moves forward (the numbers do not run in order). Recommendations
(`requirement_type = recommendation`, order 288.2) are counted on their own line, never added to the
rules a review compares.

Nothing but ids and counts is printed: no sentence, clause number, filename or page (CLAUDE.md rule 1).
`--csv` writes one row per problem rule (id, standard id, the problem) to a path OUTSIDE the repository
for the person who fixes it. A live-shaped database path is refused. No model, no network.

    python scripts/library_order_report.py --db <library-copy.sqlite> [--standard <document id> ...] [--csv out.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))


def _words(text: object) -> str:
    return " ".join(str(text or "").lower().split())


def _clause_key(clause: object) -> tuple[int, ...] | None:
    parts = re.findall(r"\d+", str(clause or ""))
    return (
        tuple(int(p) for p in parts)
        if parts and re.match(r"^\s*\d", str(clause))
        else None
    )


def report_for(rows: list[sqlite3.Row]) -> tuple[dict, list[tuple[str, str]]]:
    """(counts, problems) for the rules of ONE standard, rows in storage order."""
    problems: list[tuple[str, str]] = []
    by_type: dict[str, int] = {}
    seen: dict[str, str] = {}
    duplicates = no_clause = no_page = backward = 0
    previous = None  # (page, clause key) of the last rule that had both
    for row in sorted(
        rows, key=lambda r: (r["page"] is None, r["page"] or 0, r["rowid"])
    ):
        kind = row["requirement_type"] or "untyped"
        by_type[kind] = by_type.get(kind, 0) + 1
        if not str(row["clause"] or "").strip():
            no_clause += 1
            problems.append((row["id"], "no clause number"))
        if row["page"] is None:
            no_page += 1
            problems.append((row["id"], "no page"))
        text = _words(row["requirement_text"])
        if text in seen:
            duplicates += 1
            problems.append((row["id"], f"duplicate of {seen[text]}"))
        else:
            seen[text] = row["id"]
        key = _clause_key(row["clause"])
        if key is not None and row["page"] is not None:
            if previous and row["page"] > previous[0] and key < previous[1]:
                backward += 1
                problems.append(
                    (row["id"], "clause goes backward while the page advances")
                )
            previous = (row["page"], key)
    recommendations = by_type.get("recommendation", 0)
    counts = {
        "rules": len(rows) - recommendations,
        "recommendations": recommendations,
        "by_type": dict(sorted(by_type.items())),
        "without_clause": no_clause,
        "without_page": no_page,
        "duplicate_rows": duplicates,
        "clause_backward_while_page_advances": backward,
    }
    return counts, problems


def run(
    db_path: Path, standards: list[str] | None = None
) -> tuple[dict, list[tuple[str, str, str]]]:
    from rehearse_requirement_reextraction import refuse_live

    path = refuse_live(db_path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        ids = standards or [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT standard_document_id FROM standard_requirements"
                " WHERE superseded_at IS NULL ORDER BY 1"
            )
        ]
        out: dict[str, dict] = {}
        all_problems: list[tuple[str, str, str]] = []
        for sid in ids:
            rows = conn.execute(
                "SELECT rowid, id, clause, page, requirement_text, requirement_type"
                " FROM standard_requirements WHERE standard_document_id = ?"
                " AND superseded_at IS NULL",
                (sid,),
            ).fetchall()
            out[sid], problems = report_for(rows)
            all_problems += [(sid, rid, why) for rid, why in problems]
    finally:
        conn.close()
    return out, all_problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--standard", action="append")
    ap.add_argument("--csv", type=Path)
    args = ap.parse_args(argv)
    if args.csv and (args.csv.resolve() == REPO or REPO in args.csv.resolve().parents):
        print("refused: write the csv outside the repository")
        return 2
    counts, problems = run(args.db, args.standard)
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["standard_document_id", "requirement_id", "problem"])
            writer.writerows(problems)
    print(json.dumps(counts, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
