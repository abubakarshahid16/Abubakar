"""One-off correction: `standards_inventory.backfill_cover_metadata`'s first
version stored `effective_date` as the cover page's own prose ("18 August
2019") instead of ISO `YYYY-MM-DD`, discovered when the owner asked for the
inventory's edition coverage and to confirm the ISO claim (2026-09-24). The
code is already fixed (`_to_iso_date`); this script corrects the rows that
were already written under the old behaviour.

SCOPE, DELIBERATELY NARROW. Only rows with `effective_date_evidence` set (this
system's OWN cover-page backfill wrote them) and whose current `effective_date`
is NOT already `YYYY-MM-DD`-shaped are touched - never a value a human typed
through the UI, and never a row already in the correct shape. The QUOTE in
`effective_date_evidence` (the document's own words) is re-parsed with the
same `_to_iso_date` the extractor uses, so the corrected value is derived by
the identical logic a fresh backfill would produce, not a second guess.

A row whose stored quote does not parse (should not happen - it was
produced by the same extractor) is left untouched and reported, not
silently cleared.

    python scripts/fix_effective_date_iso.py --db <copy.sqlite>
    python scripts/fix_effective_date_iso.py --db backend/data/rag_intelligence.sqlite --live
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--backup-dir", type=Path, default=None)
    args = ap.parse_args()
    target = args.db.resolve()

    from app import db, live_guard  # noqa: E402
    from app.config import settings  # noqa: E402
    from app.standards_inventory import _to_iso_date  # noqa: E402

    summary: dict = {"database": str(target)}
    if args.live:
        clearance = live_guard.prepare_live_write(
            target, reason="B5 standards-inventory effective_date ISO correction",
            backup_dir=args.backup_dir)
        summary["rollback_point"] = clearance.backup_path
    elif live_guard.is_live_shaped(target):
        raise SystemExit("refusing: that is a live database; pass --live")
    settings.db_path = target
    db.reset_connection()
    conn = db.connect()

    rows = conn.execute(
        "SELECT document_id, document_number, effective_date,"
        " effective_date_evidence FROM document_classification"
        " WHERE effective_date_evidence IS NOT NULL"
        " AND effective_date IS NOT NULL").fetchall()

    fixed, already_iso, unparseable = [], 0, []
    for row in rows:
        current = row["effective_date"]
        if len(current) == 10 and current[4] == "-" and current[7] == "-":
            already_iso += 1
            continue
        evidence = json.loads(row["effective_date_evidence"])
        iso = _to_iso_date(evidence["quote"].split(":", 1)[-1].strip())
        if iso is None:
            # The quote includes the label ("Issue Date: 18 August 2019");
            # try again stripping any leading label word.
            import re
            m = re.search(r"(\d{1,2}\s+\S+\s+\d{4}|\S+\s+\d{1,2},?\s+\d{4}"
                          r"|\d{4}-\d{2}-\d{2})", evidence["quote"])
            iso = _to_iso_date(m.group(1)) if m else None
        if iso is None:
            unparseable.append({"document_id": row["document_id"],
                                "document_number": row["document_number"],
                                "quote": evidence["quote"]})
            continue
        with conn:
            conn.execute(
                "UPDATE document_classification SET effective_date = ?"
                " WHERE document_id = ?", (iso, row["document_id"]))
        fixed.append({"document_id": row["document_id"],
                     "document_number": row["document_number"],
                     "before": current, "after": iso})

    summary.update({"candidates": len(rows), "already_iso": already_iso,
                    "fixed": len(fixed), "unparseable": len(unparseable),
                    "unparseable_rows": unparseable,
                    "fixed_sample": fixed[:5]})
    db.reset_connection()
    live_guard.revoke_all()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
