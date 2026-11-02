"""#805 plan change 6, part A: move a compile's rows into the rulebook's version 2 tables, on a COPY of the database.

    python scripts/rulebook_v2.py --db <copy> --migrate-only
    python scripts/rulebook_v2.py --db <copy> --standard A --standard B --standard C --standard D

Sends nothing and calls no model: USD 0. Needs RULEBOOK_V2_ENABLED. A live-shaped --db is refused. Run again it adds
nothing. Stdout is one line of JSON, counts only: for each standard its rules, applicability filled, quotes verified,
dropped by reason, and version 1 beside version 2. No document text.

Exit: 0 done; 3 switch off, nothing was read or written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from compile_standards import _chosen  # noqa: E402
from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_OFF = 3


def run(db_path: Path, wanted: list[str], *, emit=print) -> int:
    from app.config import settings

    if not settings.rulebook_v2_enabled:
        emit(
            json.dumps(
                {"stopped": "RULEBOOK_V2_ENABLED is off: nothing was read or written."}
            )
        )
        return EXIT_OFF
    settings.db_path = refuse_live(db_path)
    from app import compiled_rule_report, rulebook_v2, rulebook_v2_ingest
    from app.db import connect

    conn = connect()
    rulebook_v2.ensure_schema(conn)
    documents = _chosen(conn, wanted)
    ingested = {
        label: rulebook_v2_ingest.ingest_latest(conn, document_id)
        for document_id, label in sorted(documents.items(), key=lambda kv: kv[1])
    }
    emit(
        json.dumps(
            {
                "tables": list(rulebook_v2.TABLES),
                "ingested": ingested,
                "side_by_side": compiled_rule_report.side_by_side(conn, documents),
                "integrity_problems": rulebook_v2.integrity_problems(conn),
            },
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument(
        "--db", required=True, type=Path, help="a COPY; a live-shaped path is refused"
    )
    ap.add_argument(
        "--standard",
        action="append",
        default=[],
        help="a document id or a standard's number",
    )
    ap.add_argument(
        "--migrate-only", action="store_true", help="create the tables and stop"
    )
    args = ap.parse_args(argv)
    if not args.migrate_only and not args.standard:
        ap.error("name a --standard, or say --migrate-only")
    return run(args.db, [] if args.migrate_only else args.standard)


if __name__ == "__main__":
    sys.exit(main())
