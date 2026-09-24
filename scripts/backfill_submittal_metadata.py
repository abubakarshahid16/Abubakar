"""Backfill equipment_type/discipline/service/project for every
CONTRACTOR_SUBMITTAL already in the system, using the SAME functions the
live ingestion hook calls (`ingest.py:766-768`) - not a second, one-off
implementation.

WHY THIS EXISTS. #176's classifiers are real and correctly wired into
ingestion (`_finish_if_embedded`, called on the PARTIALLY_SEARCHABLE ->
READY transition), but that is an EVENT HOOK, not a re-scan: it never
fires again for a document already sitting at READY. The 3 real
regression submittals were ingested before #176's code existed, so it
never ran for them - found 2026-09-25 when `applicability_with_reasons`
showed all three with every classification field still NULL. Not a false
claim, not a wrong table: a genuine gap between "the capability exists"
and "it has been applied to what is already here."

STANDING RULE FROM HERE ON (owner instruction, 2026-09-25): any new
ingest-time enrichment ships WITH a backfill for documents already in the
system. This script is the template for that rule - call the exact
functions the live hook calls, guarded by live_guard, unknown stays
unknown.

    python scripts/backfill_submittal_metadata.py --db <copy.sqlite>
    python scripts/backfill_submittal_metadata.py --db backend/data/rag_intelligence.sqlite --live
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
    ap.add_argument("--live", action="store_true",
                    help="write a live database, after the A5 backup + restore drill")
    ap.add_argument("--backup-dir", type=Path, default=None)
    args = ap.parse_args()
    target = args.db.resolve()

    from app import classification, db, live_guard
    from app.config import settings

    summary: dict = {"database": str(target)}
    if args.live:
        clearance = live_guard.prepare_live_write(
            target, reason="B5/#176 submittal-metadata backfill "
                           "(same functions the live ingest hook calls)",
            backup_dir=args.backup_dir)
        summary["rollback_point"] = clearance.backup_path
    elif live_guard.is_live_shaped(target):
        raise SystemExit("refusing: that is a live database; pass --live")
    settings.db_path = target
    db.reset_connection()
    conn = db.connect()

    doc_ids = [r["id"] for r in conn.execute(
        "SELECT d.id FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id"
        " WHERE c.document_role = 'CONTRACTOR_SUBMITTAL'")]

    changes = []
    for doc_id in doc_ids:
        equipment_evidence = classification.classify_equipment_type_for_submittal(doc_id)
        metadata_evidence = classification.classify_metadata_for_submittal(doc_id)
        written = {}
        if equipment_evidence is not None:
            written["equipment_type"] = equipment_evidence.equipment_type
        for field, evidence in (metadata_evidence or {}).items():
            written[field] = getattr(evidence, "value", None) or str(evidence)
        if written:
            changes.append({"document_id": doc_id, "written": written})

    row = conn.execute(
        "SELECT COUNT(*) AS n FROM document_classification"
        " WHERE document_role = 'CONTRACTOR_SUBMITTAL'").fetchone()
    still_null = conn.execute(
        "SELECT document_id, equipment_type, discipline, service, project"
        " FROM document_classification WHERE document_role = 'CONTRACTOR_SUBMITTAL'"
    ).fetchall()

    summary.update({
        "submittals": row["n"],
        "changed": len(changes),
        "changes": changes,
        "fields_after": [
            {"document_id": r["document_id"], "equipment_type": r["equipment_type"],
             "discipline": r["discipline"], "service": r["service"],
             "project": r["project"]}
            for r in still_null],
    })
    db.reset_connection()
    live_guard.revoke_all()
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
