"""Rehearse the requirement re-extraction of #599 on a COPY of a database.

WHY THIS EXISTS (#640). #599 re-extracts every standard's requirements after
the W2b fixes. Before #640 a re-extraction DELETED every unconfirmed
requirement and orphaned the review findings citing them (about 117,000 on a
copy). Now it keeps a requirement it produces again and marks the rest
superseded. This script runs exactly that - `extract_requirements` then
`extract_table_values`, the extraction job's two steps - for every
COMPANY_STANDARD in the database given, and prints the counts that say
whether it was safe, before and after.

IT REFUSES THE LIVE DATABASE. A path shaped like any checkout's live file
(`backend/data/rag_intelligence.sqlite`, see `live_guard.is_live_shaped`), or
the same file as this checkout's live database, is refused before anything is
opened. Make the copy first (all three WAL files together - CLAUDE.md,
"Tooling traps"), for example with `scripts/reextract_on_copy.py`'s copy step
or `live_guard.diagnostic_copy()`.

Output: counts and document ids only, never document text.

    python scripts/rehearse_requirement_reextraction.py --db <copy>/rehearsal.sqlite
    python scripts/rehearse_requirement_reextraction.py --db <copy> --doc <id> --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"


def refuse_live(path: Path) -> Path:
    """The database to rehearse on, or SystemExit if it is (or is shaped
    like) a live database, or does not exist."""
    from app import live_guard

    resolved = path.resolve()
    if live_guard.is_live_shaped(resolved):
        raise SystemExit(f"refusing: {resolved} is a live database path. "
                         "Rehearse on a copy.")
    if LIVE.exists() and resolved.exists() and os.path.samefile(resolved, LIVE):
        raise SystemExit(f"refusing: {resolved} is this checkout's live database. "
                         "Rehearse on a copy.")
    if not resolved.exists():
        raise SystemExit(f"no database at {resolved}")
    return resolved


def _one(conn: sqlite3.Connection, sql: str) -> int:
    try:
        return int(conn.execute(sql).fetchone()[0] or 0)
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return 0
        raise


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    """What the rehearsal is judged on. Every number states its boundary:
    the whole database given, all standards in it."""
    active = "superseded_at IS NULL"
    return {
        "requirements_total": _one(conn, "SELECT COUNT(*) FROM standard_requirements"),
        "requirements_active": _one(
            conn, f"SELECT COUNT(*) FROM standard_requirements WHERE {active}"),
        "requirements_superseded": _one(
            conn, "SELECT COUNT(*) FROM standard_requirements WHERE superseded_at IS NOT NULL"),
        # A table cell met twice is one requirement (#594): extra ACTIVE rows
        # with the same standard + identity are duplicates within a table.
        "duplicate_table_cells_active": _one(conn, f"""
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements
               WHERE identity_key IS NOT NULL AND {active}
               GROUP BY standard_document_id, identity_key HAVING n > 1)"""),
        "duplicate_sentences_active": _one(conn, f"""
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements
               WHERE COALESCE(requirement_type, '') != 'table_value' AND {active}
               GROUP BY standard_document_id, clause, requirement_text HAVING n > 1)"""),
        # #673: repeats counted PLAINLY - the same standard and the same
        # requirement text, whatever the clause, the type or the identity key
        # (rows written before #594 have no identity key, so the two counts
        # above said 0 for exactly the rows #599 cleans up). Extra rows beyond
        # the first of each text; the denominators are requirements_active and
        # requirements_total above. Superseded rows are counted in the second.
        "repeated_rows_active": _one(conn, f"""
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements WHERE {active}
               GROUP BY standard_document_id, requirement_text HAVING n > 1)"""),
        "repeated_table_cell_rows_active": _one(conn, f"""
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements
               WHERE requirement_type = 'table_value' AND {active}
               GROUP BY standard_document_id, requirement_text HAVING n > 1)"""),
        "repeated_rows_including_superseded": _one(conn, """
            SELECT COALESCE(SUM(n - 1), 0) FROM (
              SELECT COUNT(*) AS n FROM standard_requirements
               GROUP BY standard_document_id, requirement_text HAVING n > 1)"""),
        "confirmed": _one(
            conn, "SELECT COUNT(*) FROM standard_requirements WHERE confirmed_by IS NOT NULL"),
        "confirmed_active": _one(
            conn, f"SELECT COUNT(*) FROM standard_requirements"
                  f" WHERE confirmed_by IS NOT NULL AND {active}"),
        # The number #640 exists to keep from growing.
        "findings_requirement_unresolved": _one(conn, """
            SELECT COUNT(*) FROM review_findings f
             WHERE f.requirement_id IS NOT NULL AND NOT EXISTS (
               SELECT 1 FROM standard_requirements r WHERE r.id = f.requirement_id)"""),
        "findings_on_superseded_requirement": _one(conn, """
            SELECT COUNT(*) FROM review_findings f
              JOIN standard_requirements r ON r.id = f.requirement_id
             WHERE r.superseded_at IS NOT NULL"""),
    }


def rehearse(db_path: Path, only: list[str] | None = None) -> dict:
    from app import db, standards, submittal_review
    from app.config import settings

    settings.db_path = refuse_live(db_path)
    db.reset_connection()
    submittal_review.ensure_schema()   # migrates the COPY (adds the #640 columns)
    conn = db.connect()
    before = counts(conn)
    every = frozenset(r["id"] for r in conn.execute("SELECT id FROM documents"))
    ids = only or [r["document_id"] for r in conn.execute(
        "SELECT document_id FROM document_classification"
        " WHERE document_role = 'COMPANY_STANDARD' ORDER BY document_id")]
    per_document, failed = [], []
    for doc in ids:
        try:
            sentences = standards.extract_requirements(doc, allowed_document_ids=every)
            cells = standards.extract_table_values(doc, allowed_document_ids=every)
        except Exception as exc:  # noqa: BLE001 - one bad standard must not stop the rest
            failed.append({"document_id": doc, "error": type(exc).__name__})
            continue
        per_document.append({
            "document_id": doc,
            "requirements": sentences.get("requirements", 0),
            "kept": sentences.get("kept", 0),
            "superseded": sentences.get("superseded", 0) + cells.get("superseded", 0),
            "table_values": cells.get("values", 0),
        })
    after = counts(db.connect())
    db.reset_connection()
    return {"database": str(settings.db_path), "standards": len(ids),
            "failed": failed, "before": before, "after": after,
            "per_document": per_document}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, type=Path,
                    help="a COPY of the database (the live one is refused)")
    ap.add_argument("--doc", action="append", help="only this standard (repeatable)")
    ap.add_argument("--json", type=Path, help="also write the summary here")
    args = ap.parse_args(argv)
    summary = rehearse(args.db, args.doc)
    width = max(len(k) for k in summary["before"])
    print(f"database: {summary['database']}")
    print(f"standards re-extracted: {summary['standards'] - len(summary['failed'])}"
          f" of {summary['standards']} (failed: {len(summary['failed'])})")
    print(f"{'count':<{width}}  {'before':>9}  {'after':>9}")
    for key in summary["before"]:
        print(f"{key:<{width}}  {summary['before'][key]:>9}  {summary['after'][key]:>9}")
    for label, side in (("before", summary["before"]), ("after", summary["after"])):
        total, repeated = side["requirements_active"], side["repeated_rows_active"]
        share = f" ({repeated / total:.1%})" if total else ""
        print(f"repeated rows {label}: {repeated} of {total} active rows{share}")
    if args.json:
        args.json.write_text(json.dumps(summary, indent=1), encoding="utf-8")
    ok = (summary["after"]["confirmed"] == summary["before"]["confirmed"]
          and summary["after"]["findings_requirement_unresolved"]
          <= summary["before"]["findings_requirement_unresolved"])
    print("SAFE: no confirmed requirement lost, no finding newly unresolved" if ok
          else "NOT SAFE: see the counts above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
