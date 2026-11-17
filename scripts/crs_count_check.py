"""Count check for a review's CRS files (owner, 15 Nov 2026: completeness is a hard rule). READ ONLY.

    python scripts/crs_count_check.py <run id> [--db <COPY of the database>]

Prints, for the paper of the run: the points on the page, the lines in the database, the rows in each CRS file as built, and the cut
cells with and without their mark. Exit 0 when every count agrees and no cut is unmarked; exit 1 on any difference (it says which points
are missing, by name and page); exit 2 when the run is not found. Counts only: no document text is printed.

It uses the app's own database connection, so a live database is refused unless this process may open it (the server's own check
route `GET /api/reviews/papers/<paper id>/crs/check` gives the same numbers on a running server)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_id")
    ap.add_argument("--db", help="a COPY of the database (default: the app's own setting)")
    args = ap.parse_args(argv)
    from app.config import settings

    if args.db:
        db_path = Path(args.db).resolve()
        settings.data_dir, settings.db_path = db_path.parent, db_path
    settings.startup_warmup = False
    from app import access, crs_completeness, db

    conn = db.connect()
    row = conn.execute("SELECT submittal_document_id FROM review_runs WHERE id = ?", (args.run_id,)).fetchone()
    if row is None:
        print(f"no review run {args.run_id}")
        return 2
    paper = row["submittal_document_id"]
    got = crs_completeness.checked_files(paper, access.unrestricted_scope())
    team, contractor = got["team"][1], got["contractor"][1]
    d = team["database"]
    print(f"run {args.run_id}  paper {paper}")
    print(f"points on the page      {team['page']}")
    print(f"lines in the database   {d['total']}  (AI {d['ai']}, rule check {d['rule_check']}, added {d['added']})")
    print(f"rows in the team file   {team['rows_in_file']}")
    print(f"rows in the contractor  {contractor['rows_in_file']}  (accounted with the points not issued: {contractor['accounted']})")
    print(f"cut cells with mark and full text {team['cut_cells_marked']}; cut cells without mark or full text {team['cut_problems']}")
    if team.get("stored_text_unchecked"):
        print(f"NOT CHECKED: {team['stored_text_unchecked']}")
    bad = False
    for name, r in (("team", team), ("contractor", contractor)):
        if not r["ok"]:
            bad = True
            print(f"DIFFERENT ({name}): {r['sentence']}")
    print("DIFFERENT" if bad else "all counts agree")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
