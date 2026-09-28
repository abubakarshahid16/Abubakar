"""Real-data check for permanent CRS comment numbers (feat/crs-permanent-numbers).

WHY. The unit and route tests prove the rules on a synthetic sheet. This runs
the real composition over the owner's REAL review runs, to show it neither
crashes on a real run's shape nor gives two comments one number, and that a
number does not change between two exports.

SAFE ON THE LIVE SYSTEM. Everything runs against `live_guard.diagnostic_copy()`
- a WAL-safe copy in a temporary folder, never the live file. The numbers it
mints go into that copy and are thrown away with it. It needs no server, and
changes no document, review or number in the real database.

WHAT IT PRINTS. Run ids (opaque), counts and the numbers themselves
("CRS-<label>-001"). Never a comment, a requirement, a value or a file name.
Note the label IS the submittal number when one was captured - print only
counts with --counts-only if that should not appear on screen.

Usage, from the repo root with the venv active (server may be running):

    python scripts/verify_crs_numbers_on_real_runs.py
    python scripts/verify_crs_numbers_on_real_runs.py --limit 5 --counts-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=10, help="most recent completed runs to check")
    ap.add_argument("--counts-only", action="store_true", help="print no CRS numbers")
    args = ap.parse_args(argv)

    from app import db, live_guard
    from app.config import settings

    live = Path(settings.db_path)
    if not live.is_file():
        print(f"STOP - no database at {live}. Run this on the machine with the real data.")
        return 1
    copy = live_guard.diagnostic_copy(live)
    print(f"Working on a disposable copy: {copy} (live file untouched)")
    settings.db_path = copy
    db.reset_connection()
    db.init_db()  # creates crs_comment_numbers in the COPY only

    from app import access, crs_numbers
    from app import main as app_main

    scope = access.unrestricted_scope()
    runs = [r["id"] for r in db.connect().execute(
        "SELECT id FROM review_runs WHERE completed_at IS NOT NULL"
        " ORDER BY completed_at DESC LIMIT ?", (args.limit,))]
    print(f"Completed review runs checked: {len(runs)}")

    failures = 0
    totals = {"rows": 0, "confirmed": 0, "numbered": 0}
    for run in runs:
        try:
            before, _m, _n, _s = app_main._crs_content(run, scope, "internal")
            app_main._mint_crs_numbers(run, scope)
            first, _m, _n, _s = app_main._crs_content(run, scope, "internal")
            second, _m, _n, _s = app_main._crs_content(run, scope, "internal")
        except Exception as exc:  # noqa: BLE001 - report, never stop the scan
            failures += 1
            print(f"  {run[:14]}  EXCEPTION {type(exc).__name__}: {exc}")
            continue
        confirmed = [r for r in first if r.get("engineer_confirmed")]
        refs = [r["crs_ref"] for r in first if r.get("crs_ref")]
        problems = []
        if len(before) != len(first):
            problems.append(f"row count changed {len(before)} -> {len(first)}")
        if len(refs) != len(set(refs)):
            problems.append("two rows share one number")
        if [r.get("crs_ref") for r in first] != [r.get("crs_ref") for r in second]:
            problems.append("numbers changed between two exports")
        unnumbered = sum(1 for r in confirmed if not r.get("crs_ref"))
        if unnumbered:
            problems.append(f"{unnumbered} confirmed row(s) left without a number")
        failures += bool(problems)
        totals["rows"] += len(first)
        totals["confirmed"] += len(confirmed)
        totals["numbered"] += len(refs)
        shown = "" if args.counts_only else (f"  e.g. {refs[0]}" if refs else "")
        print(f"  {run[:14]}  rows={len(first)} confirmed={len(confirmed)} "
              f"numbered={len(refs)}{shown}  {'PROBLEM: ' + '; '.join(problems) if problems else 'ok'}")

    db.reset_connection()
    print("\nSUMMARY (counts only)")
    print(f"  Runs: {len(runs)}  Rows: {totals['rows']}  Engineer-confirmed rows: "
          f"{totals['confirmed']}  Numbered: {totals['numbered']}  Runs with a problem: {failures}")
    if runs and not totals["confirmed"]:
        print("  NOTE: no row on these runs is engineer-confirmed yet, so none is numbered -"
              " that is the rule (drafts get no number), not a failure. Confirm one comment"
              " in the app and re-run this to see a number minted.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
