"""#946: how many standards each selection route adds, for a real submittal.

Runs `app.applicability.route_counts` (read-only, `persist=False` - nothing
is written) against one submittal and prints: the library size, how many
standards each selection method (`referenced`, `equipment_type`,
`governing_standard`, `scope`, `service`, `project`, `possible_citation`,
`discipline`, `semantic`) ended up the STRONGEST route for, how many of those
are `included` after B5's evidence filter, and how many library standards no
route touched at all. Counts only - never a document, a clause or a quote
(CLAUDE.md rule 1).

Run this BEFORE applying #946's fix and again AFTER, on the same submittal,
to measure the fix's actual effect (the "~280 standards" PF1 finding was
real-corpus, not reproducible in the cloud lane - this is the exact
measurement to re-run on PF1 sheets 1 and 2 to cross-check the invented-
fixture numbers in the PR).

ON A COPY ONLY, same convention as `pilot_ai_requirements.py` and
`rehearse_requirement_reextraction.py`: a path shaped like any checkout's
live database is refused before anything is opened.

    python scripts/measure_applicability_routes.py --db <copy.sqlite> \\
        --submittal <document_id> --library <doc_id> [<doc_id> ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"


def refuse_live(path: Path) -> Path:
    from app import live_guard

    resolved = path.resolve()
    if live_guard.is_live_shaped(resolved) or (
            LIVE.exists() and resolved.exists() and os.path.samefile(resolved, LIVE)):
        raise SystemExit(f"refusing: {resolved} is a live database. Run this on a copy.")
    if not resolved.exists():
        raise SystemExit(f"no database at {resolved}")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--submittal", required=True, dest="submittal_document_id")
    parser.add_argument("--library", required=True, nargs="+", dest="library_document_ids",
                        help="the standard document ids the caller may read, plus the "
                             "submittal's own id")
    args = parser.parse_args(argv)

    refuse_live(args.db)
    from app import applicability
    from app.config import settings
    from app.db import reset_connection

    settings.db_path = args.db.resolve()
    reset_connection()

    allowed = frozenset({args.submittal_document_id, *args.library_document_ids})
    report = applicability.route_counts(args.submittal_document_id, allowed_document_ids=allowed)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
