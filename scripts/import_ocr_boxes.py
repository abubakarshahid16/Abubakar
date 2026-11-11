#!/usr/bin/env python
"""Load the OCR box file of a rule book's scanned pages into a database with the SERVER STOPPED (order 12, N7).

    AGENT_REVIEW_ENABLED=true python scripts/import_ocr_boxes.py --boxes <data dir>/labels/ocr-boxes.json \\
        [--db <database>] [--data-dir <dir>] [--expect-stored N]

Same pattern and same helpers as `scripts/import_rule_label_files.py` (one home): the switch must be on, the file must be a
.json file inside the data directory, the server must be stopped, a live-shaped database is written only after
`live_guard.prepare_live_write` (verified backup and restore drill). The SAME function as the route
(`ocr_box_import.import_pages`) checks every page again by code. Counts only are printed, never a word of a page.

Run it BEFORE the label re-import: a label on a scanned page is judged by the boxes stored for that page.

Exit codes: 0 loaded as expected; 1 refused before any write; 3 loaded but the counts are not what was expected
(`--expect-stored` differs from stored + unchanged). Idempotent: a second run stores nothing and counts every page unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import import_rule_label_files as base  # noqa: E402

from app import db, live_guard, ocr_box_import, rule_label_import  # noqa: E402
from app.config import settings  # noqa: E402
from app.rule_label_schema import SwitchedOff, require_on  # noqa: E402

REASON = "import the OCR boxes of the rule books (order 12, N7)"
Refused = base.Refused


def load(
    boxes: str,
    *,
    db_path: str | None = None,
    data_dir: str | None = None,
    port: int | None = None,
    backup_dir: str | None = None,
    check_server: bool = True,
) -> dict:
    """Check, then load the box file. Returns {"boxes": counts, "backup": bool}. Raises `Refused`."""
    try:
        require_on()
    except SwitchedOff as exc:
        raise Refused(str(exc)) from None
    if data_dir:
        settings.data_dir = Path(data_dir).resolve()
    if db_path:
        settings.db_path = Path(db_path).resolve()
    if check_server and base.server_answers(
        port if port is not None else settings.port
    ):
        raise Refused("something answers on the server's port: stop the server first")
    try:
        pages, sha = ocr_box_import.read_file(
            rule_label_import.resolve_data_path(boxes)
        )
    except (rule_label_import.ImportPathError, ValueError) as exc:
        raise Refused(f"box file: {exc}") from None
    if not Path(settings.db_path).is_file():
        raise Refused("no such database")
    backed_up = False
    if (
        live_guard.is_live_shaped(settings.db_path)
        and not live_guard.is_server_process()
    ):
        try:
            live_guard.prepare_live_write(
                settings.db_path, reason=REASON, backup_dir=backup_dir
            )
        except live_guard.LiveWriteRefused as exc:
            raise Refused(f"live guard: {exc}") from None
        backed_up = True
    db.reset_connection()
    conn = db.connect()
    try:
        try:
            out = ocr_box_import.import_pages(conn, pages, sha)
        except ocr_box_import.BoxSchemaError as exc:
            raise Refused(str(exc)) from None
    finally:
        db.reset_connection()
    return {"boxes": out, "backup": backed_up}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--boxes", required=True, help="the box file, inside the data directory"
    )
    ap.add_argument(
        "--db", default=None, help="the database (default: the configured one)"
    )
    ap.add_argument(
        "--data-dir", default=None, help="the data directory the file must be inside"
    )
    ap.add_argument(
        "--port", type=int, default=None, help="the server's port to check is silent"
    )
    ap.add_argument(
        "--backup-dir",
        default=None,
        help="live database only: the folder for the verified backup",
    )
    ap.add_argument("--expect-stored", type=int, default=None)
    a = ap.parse_args(argv)
    try:
        got = load(
            a.boxes,
            db_path=a.db,
            data_dir=a.data_dir,
            port=a.port,
            backup_dir=a.backup_dir,
        )
    except Refused as exc:
        print(f"REFUSED | {exc}", flush=True)
        return 1
    print("BOXES " + json.dumps(got["boxes"], sort_keys=True))
    by_reason = {k: n for k, n in got["boxes"]["refused"].items() if n}
    print("REFUSED BY REASON " + json.dumps(by_reason, sort_keys=True))
    print(f"BACKUP verified before the write: {got['backup']}")
    have = got["boxes"]["stored"] + got["boxes"]["unchanged"]
    if a.expect_stored is not None and a.expect_stored != have:
        print(
            f"COUNTS NOT AS EXPECTED | pages held {have}, expected {a.expect_stored}",
            flush=True,
        )
        return 3
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
