"""Score one review run against an engineer's blind-test answer key.

The procedure (who writes the key, when, and how its hash proves it came
first) is docs/blind-test.md. This script is the last step: it reads the run's
CRS rows exactly as the product composes them - the internal copy, every row
the machine produced, confirmed or not - and scores them with
`app.blind_test.score`.

SAFE ON THE LIVE SYSTEM. It works on a `live_guard.diagnostic_copy()` of the
database, never the live file, needs no server and changes nothing.

WHAT IT PRINTS. The key file's SHA-256 (compare it with the one recorded
before the upload), counts with their denominators, and per key line: the line
number, the expected type and the outcome. Field names only with --show-fields
- they are the engineer's words about a client document, so leave them out of
anything that leaves this machine (CLAUDE.md rule 1).

Usage, from the repo root with the venv active:

    python scripts/blind_score.py <review_run_id> gold/FINDINGS-<submittal>.csv
    python scripts/blind_score.py <review_run_id> gold/FINDINGS-<submittal>.csv --show-fields
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def _pct(part: int, whole: int) -> str:
    return f"{part} of {whole}" + (f" ({100 * part / whole:.0f}%)" if whole else "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("review_run_id")
    ap.add_argument("answer_key")
    ap.add_argument("--show-fields", action="store_true",
                    help="print each key line's field (keep it on this machine)")
    args = ap.parse_args(argv)

    from tools import blind_test
    key_path = Path(args.answer_key)
    digest = hashlib.sha256(key_path.read_bytes()).hexdigest()
    try:
        key = blind_test.read_key(key_path)
    except blind_test.AnswerKeyError as exc:
        print(f"STOP - the answer key cannot be scored: {exc}")
        return 2

    from app import access, db, live_guard
    from app.config import settings
    live = Path(settings.db_path)
    if not live.is_file():
        print(f"STOP - no database at {live}.")
        return 1
    copy = live_guard.diagnostic_copy(live)
    settings.db_path = copy
    db.reset_connection()
    db.init_db()
    from app import main as app_main
    from fastapi import HTTPException

    try:
        rows, meta, name, _stamp = app_main._crs_content(
            args.review_run_id, access.unrestricted_scope(), "internal")
    except HTTPException:
        print(f"STOP - no review run {args.review_run_id} in this database.")
        return 1
    finally:
        db.reset_connection()

    result = blind_test.score(key, rows, name)
    print(f"Answer key SHA-256: {digest}")
    print("  Compare with the hash recorded BEFORE the upload. Different means the key")
    print("  changed after the machine's answer could be seen: the score is not blind.")
    print(f"Review run: {args.review_run_id}\n")
    e = result["expected_comments"]
    print("COMMENTS THE ENGINEER EXPECTED")
    print(f"  Found, right type:     {_pct(result['found'], e)}")
    print(f"  Found, other type:     {_pct(result['found_other_type'], e)}")
    print(f"  Missed:                {_pct(result['missed'], e)}")
    print("FIELDS THE ENGINEER SAID NEED NO COMMENT")
    print(f"  False alarms:          {_pct(result['false_alarms'], result['none_lines'])}")
    print("MACHINE ROWS")
    print(f"  Not in the answer key: {_pct(result['extra_rows'], result['machine_rows'])}"
          "  (false positives only if the key covers the whole sheet)")
    if result["clause_checked"]:
        print(f"  Same clause cited:     {_pct(result['clause_agreed'], result['clause_checked'])}")
    if result["rows_not_machine_output"]:
        print(f"  Left out (engineer's own or carried forward): {result['rows_not_machine_output']}")
    if result["key_lines_for_another_submittal"]:
        print(f"  Key lines naming another submittal, skipped: "
              f"{result['key_lines_for_another_submittal']}")
    print("\nPER KEY LINE")
    for o in result["lines"]:
        field = f"  {o['field']}" if args.show_fields else ""
        row = f"  (sheet row {o['row']})" if o["row"] else ""
        print(f"  line {o['line']:>3}  expected {o['expected']:<7} -> {o['outcome']}{row}{field}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
