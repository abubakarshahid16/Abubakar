"""Compile one standard's checklist, once (#645/#833 general-path step 1).

"Standards -> checklist, by AI, once" (planner, 13 Oct): for every open clause
sentence of ONE standard (`requirement_type == statement`, not yet superseded),
ask the local model for a numeric check (field, operator, value, unit,
condition, verbatim quote), verify every part in code against the sentence,
and store what passes as a DRAFT - exactly `ai_requirements.propose_checks`,
unchanged, just run over a whole standard instead of one review's undecided
sentences, so the draft exists before any submittal is reviewed against it.
Nothing here decides a verdict: a draft becomes a requirement only when an
engineer accepts it (`POST /api/standards/clause-checks/{id}/decision`), the
same route #645 part 2 already built.

WRITES TO THE DATABASE (new `clause_check_drafts` rows only - no existing
requirement is changed, no row is deleted). Run on a COPY first. The live
database (CLAUDE.md: "only the server writes it") is written only through
`live_guard.prepare_live_write`, which takes its own verified backup and
restore drill before clearing this process - called automatically below when
`--db` is live-shaped; nothing extra to pass.

Prints counts only - sentences, asked, proposed, refused by reason, no_limit,
could_not_read, model - never a clause sentence or a quote (CLAUDE.md rule 1).

    python scripts/compile_standard.py --db <copy.sqlite> --standard <document_id>
    python scripts/compile_standard.py --db backend/data/rag_intelligence.sqlite \\
        --standard <document_id>   # live database: prepare_live_write runs first
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, type=Path, help="the database to compile into")
    parser.add_argument("--standard", required=True, dest="standard_document_id",
                        help="the standard's document id")
    parser.add_argument("--limit", type=int, default=200,
                        help="at most this many sentences asked about (default 200)")
    parser.add_argument("--model", default=None, help="override settings.ai_task_model")
    args = parser.parse_args(argv)

    from app import ai_requirements, live_guard
    from app.config import settings
    from app.db import reset_connection

    db_path = args.db.resolve()
    if not db_path.exists():
        raise SystemExit(f"no database at {db_path}")
    settings.db_path = db_path
    reset_connection()

    if live_guard.is_live_shaped(db_path):
        live_guard.prepare_live_write(
            db_path, reason=f"compile_standard {args.standard_document_id}")

    provider = ai_requirements.ai_task_runner.make_provider(args.model) if args.model else None
    report = ai_requirements.compile_standard(
        args.standard_document_id,
        allowed_document_ids=frozenset({args.standard_document_id}),
        limit=args.limit, provider=provider)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
