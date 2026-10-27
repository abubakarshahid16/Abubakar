"""Which clauses of the held API 610 copy are about each pump checklist field? (order 235.2)

The committed pump checklist (reference/datasheet_checks.json, "Centrifugal Pump")
cannot name API 610 clause numbers: nobody may read the held copy into the
repo, and the numbers were never checked. This script is run LOCALLY by whoever
holds the copy (s2 on the Mac, or an engineer), on a disposable copy of the
database. For each checklist item it lists the clause references of the
standard's requirements whose subject names the item's field, so the engineer
can confirm one clause per item and put it in the local overlay
(`<data_dir>/checklists/centrifugal_pump.json`, same shape as an item). It prints
item ids, clause references and counts. NEVER a requirement's text.

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


def clauses_for(role: str, rules: dict, rows: list[dict]) -> list[str]:
    """Clause references (distinct, in order) of the rows whose subject names the role."""
    wanted = field_words(role, rules)
    found: list[str] = []
    for row in rows:
        subject = " ".join(
            re.findall(r"[a-z0-9]+", str(row.get("subject") or "").lower())
        )
        if subject and any(w and w in subject for w in wanted) and row.get("clause"):
            found.append(str(row["clause"]))
    return list(dict.fromkeys(found))


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
                "SELECT subject, clause FROM standard_requirements WHERE superseded_at IS NULL"
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
