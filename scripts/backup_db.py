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
    """One consistent snapshot, timestamped, verified before returning.

    Refuses rather than succeeding on the wrong contents. Both of the guards
    below exist because the first version did exactly that, reproduced on the
    production machine on 2026-09-19 before either was fixed:

    * A ONE-LETTER TYPO IN THE SOURCE PATH was backed up as an empty
      database and verified ok. `sqlite3.connect` CREATES a file that does
      not exist - so the tool made an empty database at the typo, copied it,
      and `integrity_check` passed, because an empty file is internally
      consistent. The source is now opened READ-ONLY by URI, which refuses a
      missing file and can never write to the live database either.
    * TWO BACKUPS IN THE SAME SECOND SHARED A FILENAME, and the second opened
      the first's file and overwrote it: a 10-row backup silently became a
      3-row one. The stamp now carries microseconds, and the destination is
      created exclusively - see `_reserve_name` for what happens on a tie.
    * THE DESTINATION DIRECTORY WAS NEVER CHECKED, so a backup into a path
      that did not exist yet died inside `_reserve_name` with a bare
      `FileNotFoundError` naming a file nobody had asked for - and it died
      at exactly the moment a backup was being taken, before a destructive
      change. It is REFUSED here instead, naming the directory: this module
      creates nothing it was not asked to create, for the same reason the
      source is opened read-only. A backup written somewhere the operator
      did not mean is a backup nobody will look for.
    """
    source = pathlib.Path(live_path)
    if not source.is_file():
        raise FileNotFoundError(f"no database at {live_path}")
    # BEFORE the source is opened, so a refused backup leaves no handle and
    # no connection behind.
    destination = pathlib.Path(backup_dir)
    if not destination.is_dir():
        raise FileNotFoundError(
            f"no backup directory at {backup_dir}: create it first, or pass "
            "one that exists - this tool does not create it for you")
    src = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    tables = src.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%'").fetchone()[0]
    if tables == 0:
        src.close()
        raise RuntimeError(
            f"refusing to back up {live_path}: it has no tables - an empty "
            "database is never what a backup of this system should contain")

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest_file = _reserve_name(destination, stamp)
    dest_path = str(dest_file)
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


#: Suffixed names tried after the plain stamp. A clock tie takes a second
#: name; a hundred taken names is not a tie, it is something else wrong.
NAME_ATTEMPTS = 100


def _reserve_name(backup_dir: pathlib.Path, stamp: str) -> pathlib.Path:
    """Create, and return, a backup file that did not exist a moment ago.

    B30: the microsecond stamp still ties on Windows, whose clock is coarser
    than a microsecond, and the second backup then CRASHED on the exclusive
    create. A tie now takes the next free name (`-1`, `-2`, ...). The create
    stays EXCLUSIVE, so a name that exists is skipped - never opened by sqlite
    and written over. Past NAME_ATTEMPTS it raises rather than looping.
    """
    for attempt in range(NAME_ATTEMPTS):
        suffix = f"-{attempt}" if attempt else ""
        candidate = backup_dir / f"rag_intelligence-{stamp}{suffix}.sqlite"
        try:
            with open(candidate, "xb"):
                pass
        except FileExistsError:
            continue
        return candidate
    raise FileExistsError(
        f"no free backup name for stamp {stamp} in {backup_dir} "
        f"after {NAME_ATTEMPTS} attempts")


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
