"""#1525: write the audit report of stored review runs, from a COPY of the database.

    python scripts/review_audit_export.py --db ~/project/mirror/proof/<copy>.sqlite \\
        --run <run id> [--run <run id> ...] [--out <folder>]

For the owner's proof: re-export a saved run and check its counts against the bench and
the CRS export. No model is called and nothing leaves the machine. It works on a throw-away
copy made beside `--db` and never opens the live database. Files go under `--out`, else
REVIEW_AUDIT_DIR, else `~/project/mirror/proof`. It prints run ids and folders only.
A figure only the job could see (fresh calls during the run) reads "not recorded" here.

Exit codes: 0 all written, 1 a run was not written, 2 refused.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backend"))


def main(argv: list[str] | None = None) -> int:
    from tools import crs_bench

    from app import access, db, live_guard, review_audit
    from app.config import settings

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True, help="a COPY of the database")
    ap.add_argument("--run", required=True, action="append", help="a review run id")
    ap.add_argument("--out", help="the folder to write under")
    args = ap.parse_args(argv)
    path = Path(args.db).expanduser().resolve()
    if live_guard.is_live_shaped(path):
        print("refused: that is the live database. Pass a copy.")
        return 2
    if not path.is_file():
        print(f"refused: {path} does not exist")
        return 2
    old = (settings.review_audit_report_enabled, settings.review_audit_dir)
    settings.review_audit_report_enabled = True
    settings.review_audit_dir = args.out or settings.review_audit_dir
    code = 0
    try:
        with (
            crs_bench._on_copy(path, under=path.parent),
            crs_bench._models_refused([0]),
        ):
            rows = db.connect().execute("SELECT id FROM documents")
            scope = access.AccessScope(
                user_id="audit-export",
                allowed_document_ids=frozenset(r["id"] for r in rows),
            )
            for run_id in args.run:
                folder = review_audit.write(run_id, scope)
                print(f"{run_id}: {folder or 'not written'}")
                code = code if folder else 1
    finally:
        settings.review_audit_report_enabled, settings.review_audit_dir = old
    return code


if __name__ == "__main__":
    raise SystemExit(main())
