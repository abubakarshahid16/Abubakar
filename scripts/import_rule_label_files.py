#!/usr/bin/env python
"""Load the two label files (rule labels, equipment labels) into a database with the SERVER STOPPED (order 12, N3 part B).

    AGENT_REVIEW_ENABLED=true python scripts/import_rule_label_files.py \\
        --labels <data dir>/labels/rule-labels.json --equipment <data dir>/labels/rule-equipment.json \\
        [--db <database>] [--data-dir <dir>] [--expect-labels-stored N] [--expect-equipment-stored N]

WHY. The two admin routes (`POST /api/admin/rule-labels/import`, `POST /api/admin/rule-equipment/import`) need a running
server and an admin login. A script that must run once with no questions cannot log in. This command takes the same files
through the SAME functions (`rule_label_import.import_labels`, `rule_equipment.import_rows`), with the SAME checks:

  * the switch AGENT_REVIEW_ENABLED must be on (else nothing is read or written, exit 1);
  * each file must be a .json file INSIDE the data directory (`rule_label_import.resolve_data_path`, symlinks and `..`
    resolved), at most 64 MB;
  * every row is checked again by code against the rules of THIS database (the functions above);
  * the same counts are printed (read / stored / refused ...), never a quote.

WHAT IS NEW HERE (the routes do not need it, because the server owns its database):
  * the server must be STOPPED: if something answers on the server's port the command refuses (exit 1);
  * a live-shaped database is written only after `live_guard.prepare_live_write`: a verified backup and a restore drill
    (CLAUDE.md "Tooling traps"); any failure refuses and writes nothing;
  * both files are read and checked for shape BEFORE anything is written, so a bad second file does not leave half a load;
  * `--expect-labels-stored` / `--expect-equipment-stored`: exit 3 when the stored count differs (the loaded rows stay: the
    import is idempotent and nothing is deleted; the caller decides about the backup). `unknown_rule` above 0 is exit 3 too.

Exit codes: 0 loaded as expected; 1 refused before any write; 3 loaded but the counts are not what was expected.
Idempotent: a second run stores identical rows again as identical (no new event, no duplicate).
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import db, live_guard, rule_equipment, rule_label_import  # noqa: E402
from app.config import settings  # noqa: E402
from app.rule_label_schema import SwitchedOff, require_on  # noqa: E402

REASON = "import the two rule label files (order 12, N3)"


class Refused(Exception):
    """A check said no before anything was written. The message holds a cause word, never a path or a text."""


def server_answers(port: int, host: str = "127.0.0.1") -> bool:
    """True when something accepts a connection on the server's port (the server is not stopped)."""
    try:
        with socket.create_connection((host, int(port)), timeout=1.0):
            return True
    except OSError:
        return False


def load(
    labels: str,
    equipment: str,
    *,
    db_path: str | None = None,
    data_dir: str | None = None,
    port: int | None = None,
    backup_dir: str | None = None,
    check_server: bool = True,
) -> dict:
    """Check, then load both files. Returns {"labels": counts, "equipment": counts, "backup": bool}. Raises `Refused`."""
    try:
        require_on()
    except SwitchedOff as exc:
        raise Refused(str(exc)) from None
    if data_dir:
        settings.data_dir = Path(data_dir).resolve()
    if db_path:
        settings.db_path = Path(db_path).resolve()
    if check_server and server_answers(port if port is not None else settings.port):
        raise Refused("something answers on the server's port: stop the server first")
    try:
        label_rows = rule_label_import.read_file(
            rule_label_import.resolve_data_path(labels)
        )
        equipment_rows = rule_equipment.read_file(
            rule_label_import.resolve_data_path(equipment)
        )
    except (rule_label_import.ImportPathError, ValueError) as exc:
        raise Refused(f"label file: {exc}") from None
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
        out_labels = rule_label_import.import_labels(conn, label_rows)
        out_equipment = rule_equipment.import_rows(conn, equipment_rows)
    finally:
        db.reset_connection()
    return {"labels": out_labels, "equipment": out_equipment, "backup": backed_up}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--labels", required=True, help="the rule label file, inside the data directory"
    )
    ap.add_argument(
        "--equipment",
        required=True,
        help="the equipment label file, inside the data directory",
    )
    ap.add_argument(
        "--db", default=None, help="the database (default: the configured one)"
    )
    ap.add_argument(
        "--data-dir",
        default=None,
        help="the data directory the label files must be inside (default: the configured one)",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=None,
        help="the server's port to check is silent (default: the configured one)",
    )
    ap.add_argument(
        "--backup-dir",
        default=None,
        help="live database only: the folder for the verified backup (must exist; default <checkout>-backups)",
    )
    ap.add_argument("--expect-labels-stored", type=int, default=None)
    ap.add_argument("--expect-equipment-stored", type=int, default=None)
    a = ap.parse_args(argv)
    try:
        got = load(
            a.labels,
            a.equipment,
            db_path=a.db,
            data_dir=a.data_dir,
            port=a.port,
            backup_dir=a.backup_dir,
        )
    except Refused as exc:
        print(f"REFUSED | {exc}", flush=True)
        return 1
    print("LABELS " + json.dumps(got["labels"], sort_keys=True))
    print("EQUIPMENT " + json.dumps(got["equipment"], sort_keys=True))
    print(f"BACKUP verified before the write: {got['backup']}")
    bad = []
    if got["labels"]["unknown_rule"]:
        bad.append("unknown_rule above 0")
    for name, want, have in (
        ("labels", a.expect_labels_stored, got["labels"]["stored"]),
        ("equipment", a.expect_equipment_stored, got["equipment"]["stored"]),
    ):
        if want is not None and want != have:
            bad.append(f"{name} stored {have}, expected {want}")
    if bad:
        print("COUNTS NOT AS EXPECTED | " + "; ".join(bad), flush=True)
        return 3
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
