"""Which clauses of the held API 610 copy are about each pump checklist field? (order 235.2)

The committed pump checklist (reference/datasheet_checks.json, "Centrifugal Pump")
cannot name API 610 clause numbers: nobody may read the held copy into the
repo, and the numbers were never checked. This script is run LOCALLY by whoever
holds the copy (s2 on the Mac, or an engineer), on a disposable copy of the
database. For each checklist item it lists the clause references of the
standard's requirements whose subject names the item's field, so the engineer
can confirm one clause per item and put it in the local overlay
(`<data_dir>/checklists/centrifugal_pump.json`, same shape as an item). It prints
item ids, clause references and counts. NEVER a requirement's text. A clause
found only by its sentence (not its subject) carries a trailing ?.

    python scripts/pump_checklist_clauses.py [--db PATH] [--standard NAME_PART]

READ ONLY: it takes a verified copy (`live_guard.diagnostic_copy`); the live
file is opened read-only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

MAX_CLAUSES_SHOWN = 12


def field_words(role: str, rules: dict) -> list[str]:
    """The words a requirement's subject must carry for this role: the role's
    name and its printed spellings, as lowercase word groups."""
    body = rules["roles"][role]
    spellings = [role.replace("_", " "), *body.get("printed_as", [])]
    return [" ".join(re.findall(r"[a-z0-9]+", s.lower())) for s in spellings if s]


def _words(text) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def clauses_for(role: str, rules: dict, rows: list[dict]) -> list[str]:
    """Clause references (distinct, in order) of the rows about the role: first the rows whose
    SUBJECT names the field, then (marked with a trailing ?) rows whose sentence names it. The
    sentence is only searched, never printed or returned."""
    wanted = [w for w in field_words(role, rules) if w]
    strong: list[str] = []
    weak: list[str] = []
    for row in rows:
        clause = str(row.get("clause") or "")
        if not clause:
            continue
        subject = _words(row.get("subject"))
        text = _words(row.get("source_text") or row.get("requirement_text"))
        if subject and any(w in subject for w in wanted):
            strong.append(clause)
        elif any(f" {w} " in f" {text} " for w in wanted):
            weak.append(clause + "?")
    return list(dict.fromkeys(strong)) + [
        c for c in dict.fromkeys(weak) if c[:-1] not in strong
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None)
    parser.add_argument(
        "--standard", default="610", help="part of the standard's file name or number"
    )
    args = parser.parse_args()
    from app import datasheet_checks, db, live_guard
    from app.config import settings

    copy = live_guard.diagnostic_copy(args.db or settings.db_path)
    settings.db_path = copy
    db.reset_connection()
    conn = db.connect()
    ids = [
        r["id"]
        for r in conn.execute(
            "SELECT id FROM documents WHERE filename LIKE ?", (f"%{args.standard}%",)
        )
    ]
    rows = (
        [
            dict(r)
            for r in conn.execute(
                "SELECT subject, clause, source_text, requirement_text FROM standard_requirements"
                " WHERE superseded_at IS NULL"
                f" AND standard_document_id IN ({','.join('?' for _ in ids)})",
                ids,
            )
        ]
        if ids
        else []
    )
    rules = datasheet_checks.load_rules()
    print(
        f"documents matching {args.standard!r}: {len(ids)}; requirements read: {len(rows)}"
    )
    for item in rules["checklists"]["Centrifugal Pump"]["items"]:
        found = clauses_for(item["rule"]["field"], rules, rows)
        shown = ", ".join(found[:MAX_CLAUSES_SHOWN]) + (
            " ..." if len(found) > MAX_CLAUSES_SHOWN else ""
        )
        print(
            f"{item['id']}  {item['rule']['field']:<24} {len(found):>3} clause(s)  {shown}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
