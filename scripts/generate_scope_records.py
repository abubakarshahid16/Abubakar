"""Read and store each standard's verified SCOPE record (B5, `scope_records.py`),
the explicit step `standard_scope_records` docs itself as needing: "written
only by an explicit reading step; the review route only reads it."

WHY THIS EXISTS (owner request 2026-09-28). The new AI-reasoning scope
decision (`applicability_reasoning.py`, `applicability.scope_decisions_by_
reasoning`) compares a standard's scope directly against a submittal's
equipment type - but it can only compare against a scope that has already
been read once and verified. This script is that one-time read, per standard.
No manual equipment lexicon is used or needed: this reads with an empty
lexicon, which only turns off one internal cross-check (whether a covered
term happens to match a taxonomy the owner never approved) and safely falls
back to the model's own "generic scope" self-report instead.

    python scripts/generate_scope_records.py                  # report only
    python scripts/generate_scope_records.py --apply           # read + store
    python scripts/generate_scope_records.py --apply --doc ID  # one standard

REPORT (the default) reads a WAL-safe diagnostic copy and writes nothing. It
lists which standards have no stored scope record yet.

APPLY writes `standard_scope_records`, so:
  * STOP THE SERVER FIRST. Only one process may write the live database.
  * A live database is cleared through `live_guard.prepare_live_write`: a
    verified backup and a restore drill before anything is written.
  * Per standard: reads the scope passages, asks the reasoning model
    (local Ollama by default - whatever REASONING_PROVIDER is already
    configured to; this script does not change that), verifies every quote
    against the page it claims, and stores only a record with at least one
    verified item. A standard whose scope can't be found or verified is
    reported as skipped, not guessed.
  * This step is separate from turning the feature on. Set
    APPLICABILITY_REASONING_ENABLED=true in backend/.env for
    `applicability.select()` to actually use these records during a review.

Output carries document ids, filenames and short quotes already verified to
sit on the page they name - never a document's full text.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _standards_without_a_record(conn: sqlite3.Connection, only: list[str] | None) -> list[dict]:
    from app.standards import COMPANY_STANDARD

    rows = conn.execute(
        "SELECT d.id, d.filename FROM documents d"
        " JOIN document_classification c ON c.document_id = d.id"
        " WHERE c.document_role = ? AND c.superseded_by IS NULL"
        " ORDER BY d.filename", (COMPANY_STANDARD,)).fetchall()
    existing = {r["standard_document_id"] for r in conn.execute(
        "SELECT standard_document_id FROM standard_scope_records").fetchall()}
    out = []
    for row in rows:
        if only and row["id"] not in only:
            continue
        if row["id"] in existing:
            continue
        out.append({"document_id": row["id"], "filename": row["filename"]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path,
                    default=REPO / "backend" / "data" / "rag_intelligence.sqlite")
    ap.add_argument("--apply", action="store_true", help="read and store (server must be stopped)")
    ap.add_argument("--doc", action="append", help="limit to this standard's document id (repeatable)")
    args = ap.parse_args(argv)
    path = args.db.resolve()
    if not path.is_file():
        raise SystemExit(f"no database at {path}")

    from app import live_guard

    if not args.apply:
        copy = live_guard.diagnostic_copy(path) if live_guard.is_live_shaped(path) else path
        conn = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        needed = _standards_without_a_record(conn, args.doc)
        print(json.dumps({"standards_without_a_scope_record": needed}, indent=1))
        print(f"\n{len(needed)} standard(s) need a scope read. "
              "Stop the server, then run again with --apply.", file=sys.stderr)
        return 0

    from app.config import settings
    settings.db_path = path
    if live_guard.is_live_shaped(path):
        clearance = live_guard.prepare_live_write(path, reason="generate_scope_records: B5 scope reading")
        print(f"rollback point: {clearance.backup_path}", file=sys.stderr)
    from app import db, reasoning_provider as rp
    from tools import scope_records
    from app.applicability import store_scope_record

    db.reset_connection()
    conn = db.connect()
    needed = _standards_without_a_record(conn, args.doc)
    provider = rp.get_provider("reasoning", step="scope-reasoning-read")
    done, skipped = [], []
    for std in needed:
        doc_id = std["document_id"]
        try:
            passages = scope_records.find_passages(doc_id)
            result = scope_records.read_scope(doc_id, provider, lexicon={},
                                              step="scope-reasoning-read", passages=passages)
        except Exception as exc:  # noqa: BLE001 - a down model or a budget cap
            skipped.append({**std, "reason": f"reasoning call failed: {exc}"})
            continue
        if result.get("status") != "PROPOSED" or not result.get("record"):
            skipped.append({**std, "reason": result.get("why") or "no verified scope item found"})
            continue
        store_scope_record(doc_id, result["record"], prompt_version=result.get("prompt_version"))
        done.append({"document_id": doc_id, "filename": std["filename"],
                    "verified_items": result.get("verified_items")})
    print(json.dumps({"stored": done, "skipped": skipped}, indent=1))
    print(f"\nstored {len(done)}, skipped {len(skipped)}.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
