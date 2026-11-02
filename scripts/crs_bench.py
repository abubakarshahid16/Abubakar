"""The CRS test bench (#1471): saved runs through the current decide + CRS code.

    python scripts/crs_bench.py --db <COPY of the database> [--out FILE]
                                [--baseline FILE.json] [--save FILE.json] [--stored-only]

READ-ONLY on the copy you pass: every replay runs on its own throw-away copy of
it, with every model and Claude call refused. Refuses the live database - take
a copy first (`live_guard.diagnostic_copy()`). The table holds counts, ids and
checklist field names only; the copy itself stays on this machine.

Exit codes: 0 green, 1 red (a wrong verdict, a measure worse than --baseline, or
a big jump either way against it, an improvement too: the table prints the
thresholds), 2 refused, 3 the bench itself failed (an error, NOT a result: no
table is written; #1539 - a bench importing a file someone was editing once
looked 'red'). Run the bench only in a checkout nobody is editing.

Past a big jump: re-save the baseline with a table on the PR. Rows only moving from
hidden to 'needs engineer' or 'needs other document' are the lead's; a change that
adds a Pass or Fail is the owner's.

PLANTED_DEFECTS_BENCH_ENABLED=true (#1607, default off) also prints the planted-defect
table after the bench table. It never moves the exit code until its baseline is stable.

An old --out file is deleted first thing, so a refusal or a crash leaves nothing
a later reader could take for this run (#1574). Keep the copy you pass out of
the OS temp folder: a reboot empties it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))

LIVE = REPO / "backend" / "data" / "rag_intelligence.sqlite"
TRUTH = REPO / "eval" / "bench" / "truth.json"


def _settings_file(given: str | None) -> Path | None:
    """The .env to load when this checkout has none (a git worktree)."""
    if given:
        return Path(given)
    if (REPO / "backend" / ".env").exists():
        return None  # the app reads it itself
    import subprocess

    common = subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    main_env = Path(common).parent / "backend" / ".env" if common else None
    return main_env if main_env and main_env.exists() else None


EXIT_ERROR = 3


def _clear_old_out(argv: list[str] | None) -> str | None:
    """Delete an old --out before anything can fail (a wrong flag, an import, a
    refusal). Returns why --out is refused when it names a file the run reads or
    a database, which are never deleted."""
    pre = argparse.ArgumentParser(add_help=False)
    for flag in ("--out", "--db", "--truth", "--baseline"):
        pre.add_argument(flag)
    given, _ = pre.parse_known_args(argv)
    if not given.out:
        return None
    out = Path(given.out).resolve()
    reads = (given.db, given.truth or TRUTH, given.baseline)
    if ".sqlite" in out.name or out in {Path(p).resolve() for p in reads if p}:
        return f"refused: --out {out} is a database or a file this run reads"
    out.unlink(missing_ok=True)
    return None


def main(argv: list[str] | None = None) -> int:
    """Run the bench; a crash is EXIT_ERROR with its type, never 'red'."""
    try:
        return _main(argv)
    except Exception as exc:  # noqa: BLE001 - reported, never read as a result
        print(
            f"BENCH ERROR (not a result): {type(exc).__name__}: {exc}", file=sys.stderr
        )
        return EXIT_ERROR


def _planted_defects(db: Path) -> str:
    """#1607, switch PLANTED_DEFECTS_BENCH_ENABLED: printed after the table, computed
    after the gate, so it cannot move the gate until the baseline is stable."""
    from tools import planted_defects

    from app.config import settings

    if not settings.planted_defects_bench_enabled:
        return ""
    try:
        return "\n\n" + planted_defects.bench_section(db) + "\n"
    except Exception as exc:  # noqa: BLE001 - a scorer failure is not a bench result
        return f"\n\nPlanted defects: not run ({type(exc).__name__})\n"


def _main(argv: list[str] | None = None) -> int:
    refusal = _clear_old_out(argv)
    if refusal:
        print(refusal)
        return 2
    from tools import crs_bench

    from app import live_guard

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--db", required=True, help="a COPY of the database")
    ap.add_argument("--truth", default=str(TRUTH))
    ap.add_argument("--out", help="write the markdown table here (default: print it)")
    ap.add_argument("--baseline", help="a --save file to compare against (gate)")
    ap.add_argument("--save", help="save the numbers as JSON (a later --baseline)")
    ap.add_argument(
        "--stored-only",
        action="store_true",
        help="score the stored runs only; no replay",
    )
    ap.add_argument("--title", default="CRS bench")
    ap.add_argument(
        "--settings-from",
        help="the backend/.env whose switches the replay uses (default: this"
        " checkout's, else the main checkout's when run in a git worktree)",
    )
    args = ap.parse_args(argv)
    db = Path(args.db).resolve()
    if db == LIVE.resolve() or live_guard.is_live_shaped(db):
        print(
            "refused: that is the live database. Copy it first "
            "(live_guard.diagnostic_copy()) and pass the copy."
        )
        return 2
    if not db.exists():
        print(f"refused: {db} does not exist")
        return 2
    env = _settings_file(args.settings_from)
    if env is not None:
        crs_bench.use_settings_of(env)
    truth = json.loads(Path(args.truth).read_text())
    baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
    results = crs_bench.run_bench(db, truth, do_replay=not args.stored_only)
    text = crs_bench.render_markdown(
        results, truth, title=args.title, baseline=baseline
    )
    if args.save:
        crs_bench.save_results(Path(args.save), results)
    code = 1 if crs_bench.gate(results, baseline) else 0
    text += _planted_defects(db)
    if args.out:  # last: exit 3 means no table (#1574)
        Path(args.out).write_text(text)
    print(text)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
