"""#805 STEP 5: list the rulebook's book versions, restore one in one step, or release a restore, on a COPY of the database.

    python scripts/rulebook_book.py --db <copy> --list
    python scripts/rulebook_book.py --db <copy> --restore 3 --by NAME --reason "why"
    python scripts/rulebook_book.py --db <copy> --release --by NAME --reason "why"

Sends nothing and calls no model: USD 0. Needs RULEBOOK_V2_ENABLED. A live-shaped --db is refused, and this script never
calls `live_guard.prepare_live_write`: the live database is written only by the app. A restore is verified (the old
book's hash is recomputed from its members) and logged in the rulebook's event diary. Stdout is one line of JSON,
counts and ids only. Exit: 0 done; 2 refused (says why); 3 switch off, nothing was read or written.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

from rehearse_requirement_reextraction import refuse_live  # noqa: E402

EXIT_REFUSED, EXIT_OFF = 2, 3


def run(args, *, emit=print) -> int:
    from app.config import settings

    if not settings.rulebook_v2_enabled:
        emit(
            json.dumps(
                {"stopped": "RULEBOOK_V2_ENABLED is off: nothing was read or written."}
            )
        )
        return EXIT_OFF
    settings.db_path = refuse_live(args.db)
    from app import rulebook_v2, rulebook_v2_book
    from app.db import connect

    conn = connect()
    rulebook_v2.ensure_schema(conn)
    try:
        if args.restore is not None:
            out = rulebook_v2_book.restore_book(
                conn, args.restore, args.by or "", args.reason or ""
            )
        elif args.release:
            out = rulebook_v2_book.release_pin(conn, args.by or "", args.reason or "")
        else:
            out = {
                "books": rulebook_v2_book.books(conn),
                "pinned": rulebook_v2_book.active_pin(conn),
            }
    except (rulebook_v2.RuleRefused, rulebook_v2.RefusedLive) as refused:
        emit(json.dumps({"refused": str(refused)}))
        return EXIT_REFUSED
    emit(json.dumps(out, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    ap.add_argument(
        "--db", required=True, type=Path, help="a COPY; a live-shaped path is refused"
    )
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument(
        "--list", action="store_true", help="the book versions and any pinned restore"
    )
    what.add_argument(
        "--restore", type=int, metavar="N", help="pin the book to book version N"
    )
    what.add_argument(
        "--release",
        action="store_true",
        help="end a restore: the newest versions again",
    )
    ap.add_argument("--by", help="who restores or releases")
    ap.add_argument("--reason", help="why; written to the diary")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
