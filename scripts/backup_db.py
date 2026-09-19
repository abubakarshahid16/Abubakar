"""Safe backup and verify for the WAL-mode database. Phase 10.

Copying the .sqlite file alone LOSES whatever lives in the -wal file - the
project's own docs record this trap (CLAUDE.md, tooling traps). sqlite's
online backup API is the correct tool: one consistent snapshot containing
everything, taken while the app keeps running.

Pre-built and pre-tested by Cowork (4 standalone tests) on branch
cowork/phase-10-ops. One of the tests caught a real flaw in the first
version: the copy inherits WAL mode and grows its own -wal sidecar,
recreating the exact three-file trap - hence the DELETE-mode fold below.

Usage:
  python scripts/backup_db.py backup  backend/data/rag_intelligence.sqlite  <backup_dir>
  python scripts/backup_db.py verify  <backup_file>
"""
import datetime as _dt
import pathlib
import sqlite3
import sys


def backup(live_path: str, backup_dir: str) -> str:
    """One consistent snapshot, timestamped, verified before returning."""
    src = sqlite3.connect(live_path)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest_path = str(pathlib.Path(backup_dir) /
                    f"rag_intelligence-{stamp}.sqlite")
    dest = sqlite3.connect(dest_path)
    with dest:
        src.backup(dest)  # WAL-safe online copy of EVERYTHING
    # The copy inherits WAL mode from the source, so the backup would grow
    # its own -wal sidecar the moment it is touched - recreating the very
    # three-file trap this tool exists to avoid. DELETE mode checkpoints
    # and folds everything into the one file.
    dest.execute("PRAGMA journal_mode=DELETE")
    src.close()
    dest.close()
    report = verify(dest_path)
    if not report["ok"]:
        raise RuntimeError(f"backup wrote a bad file: {report}")
    return dest_path


def verify(backup_path: str) -> dict:
    """integrity_check plus per-table row counts, so a restore drill can
    compare against the live database with real numbers."""
    conn = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    tables = {}
    for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
            " AND name NOT LIKE 'sqlite_%'"):
        tables[name] = conn.execute(
            f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    conn.close()
    return {"ok": integrity == "ok", "integrity": integrity,
            "tables": tables}


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "backup":
        print(backup(sys.argv[2], sys.argv[3]))
    elif len(sys.argv) >= 3 and sys.argv[1] == "verify":
        print(verify(sys.argv[2]))
    else:
        print(__doc__)
