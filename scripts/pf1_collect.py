"""Collect one PF1 run's findings and finish its run records, counts only (#881).

    python scripts/pf1_collect.py --db COPY.sqlite --runs DIR --mode main [--model NAME]

`pf1_run.py` writes `<id>.run.json` (the review run's id, the job state, the
minutes). This reads each run from a COPY of the test server's database,
READ-ONLY, and writes beside it:

  * `<id>.findings.json` - the run's findings in `review-findings/1`
    (`review_score.py export`); it holds requirement text and stays on this
    machine;
  * the run record completed with the DECLARED `--mode` (`main`, the normal
    client workflow, or `checklists_off`, the diagnostic: you say which, it is
    never guessed), the page counts and the AI use of the stored outcome.

A record with no review run id (the run failed before it started) is left as
it is and counted. Then `pf1_report.py --set ... --runs DIR` reports. Never run
against the live database file.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))
sys.path.insert(0, str(REPO / "scripts"))

import review_score as export_cli  # noqa: E402
from tools import pf1_report  # noqa: E402


def collect(
    conn: sqlite3.Connection, runs_dir: Path, mode: str, model: str | None
) -> dict:
    done = skipped = 0
    for path in sorted(runs_dir.glob("*.run.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        run_id = record.get("review_run_id")
        if not run_id:
            skipped += 1
            continue
        row = conn.execute(
            "SELECT outcome_json FROM review_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            skipped += 1
            continue
        outcome = json.loads(row["outcome_json"]) if row["outcome_json"] else None
        findings = export_cli.export_findings(conn, run_id, model)
        (runs_dir / f"{record['id']}.findings.json").write_text(
            json.dumps(findings, indent=2) + "\n", encoding="utf-8"
        )
        path.write_text(
            json.dumps(pf1_report.complete_record(record, outcome, mode), indent=2)
            + "\n",
            encoding="utf-8",
        )
        done += 1
    return {"collected": done, "skipped_no_run": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--db", required=True, help="a COPY of the test server's database"
    )
    parser.add_argument("--runs", required=True, help="the folder pf1_run.py wrote")
    parser.add_argument(
        "--mode",
        required=True,
        choices=pf1_report.MODES,
        help="main = the normal client workflow; checklists_off = diagnostic only",
    )
    parser.add_argument("--model", help="the model's name, for the report")
    args = parser.parse_args(argv)
    try:
        conn = export_cli._open_readonly(args.db)
        counts = collect(conn, Path(args.runs), args.mode, args.model)
    except (pf1_report.ReportError, OSError, ValueError, sqlite3.Error) as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
