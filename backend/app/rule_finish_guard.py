"""Where the rule finishing line may write: only a COPY made by `prepare_work_copy`, found by a positive marker.

A database is writable by the finishing line only when it carries the table `rule_finish_work_marker` with a row that
names THIS file (its own resolved path) and the source it was copied from, and when its resolved path is none of the
protected databases (the compile source, the pages database, the app's database, the live database). Every write
function calls `require_work_copy`. The marker is created only by `prepare_work_copy` (a new copy) or `adopt_copy` (an
earlier copy, verified to hold the same rulebook tables as its source). A file-name deny list is not used: a copy renamed
to anything is still checked by what it is, not by what it is called.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import settings

MARKER = "rule_finish_work_marker"
_TABLES = ("rulebook_rule", "rulebook_version", "rulebook_provenance")


class NotAWorkCopy(PermissionError):
    """A write was refused: the database is not a marked copy, or it is a protected database."""


def _real(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.realpath(path))


def same_file(a: str | os.PathLike, b: str | os.PathLike) -> bool:
    """The same file, by resolved path or by inode (hard links, symlinks, a case-insensitive file system)."""
    if _real(a) == _real(b):
        return True
    try:
        return Path(a).exists() and Path(b).exists() and Path(a).samefile(b)
    except OSError:
        return False


def protected_paths(extra: list[str | os.PathLike] | None = None) -> list[str]:
    """The databases that are never written: the ones passed in, the app's database and the live one."""
    found = [str(p) for p in (extra or ())]
    found.append(str(settings.db_path))
    live = os.environ.get("DB_PATH")
    if live:
        found.append(live)
    return found


def db_file(conn: sqlite3.Connection) -> str:
    for _, name, path in conn.execute("PRAGMA database_list"):
        if name == "main":
            return path or ""
    return ""


def _marker_row(conn: sqlite3.Connection):
    try:
        return conn.execute(
            f"SELECT marker_id, copy_path, source_path FROM {MARKER} LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def require_work_copy(
    conn: sqlite3.Connection, protected: list[str | os.PathLike] | None = None
) -> str:
    """Return the marker id, or raise NotAWorkCopy. Called by EVERY write function."""
    path = db_file(conn)
    if not path:
        raise NotAWorkCopy(
            "refused: not a file database (a work copy is a marked file)"
        )
    row = _marker_row(conn)
    if row is None:
        raise NotAWorkCopy(
            "refused: no work-copy marker; a database is written only if prepare_work_copy made it"
        )
    if row[1] != _real(path):
        raise NotAWorkCopy(
            "refused: the marker names another file; this is not the copy it was made for"
        )
    for other in [*protected_paths(protected), row[2]]:
        if other and same_file(path, other):
            raise NotAWorkCopy(
                "refused: this is a protected database (source, pages, app or live)"
            )
    return row[0]


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _write_marker(conn: sqlite3.Connection, copy_path: str, source_path: str) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {MARKER} (marker_id TEXT PRIMARY KEY, copy_path TEXT NOT NULL, "
        "source_path TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        f"INSERT INTO {MARKER} VALUES (?,?,?,?)",
        (
            uuid.uuid4().hex,
            copy_path,
            source_path,
            datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    conn.commit()


def _refuse_protected(path: Path, protected: list[str | os.PathLike]) -> None:
    for other in protected_paths(protected):
        if other and same_file(path, other):
            raise NotAWorkCopy(f"refused: {path.name} is a protected database")


def prepare_work_copy(
    source: Path, work: Path, protected: list[str | os.PathLike] | None = None
) -> Path:
    """The copy the finishing line writes to. Refuses a protected database as the target; makes a new copy of `source`
    and marks it; an existing target must already be marked for itself (else use `adopt_copy`)."""
    protected = [*(protected or ()), source]
    _refuse_protected(work, protected)
    if not work.exists():
        work.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, work)
        conn = sqlite3.connect(work)
        try:
            _write_marker(conn, _real(work), _real(source))
        finally:
            conn.close()
        return work
    conn = sqlite3.connect(work)
    try:
        require_work_copy(conn, protected)
    finally:
        conn.close()
    return work


def adopt_copy(
    source: Path, work: Path, protected: list[str | os.PathLike] | None = None
) -> Path:
    """Mark an EXISTING file as a work copy, once, when it is verified to be a copy of `source`: not the same file, and
    the same rulebook tables with the same row counts."""
    protected = [*(protected or ()), source]
    _refuse_protected(work, protected)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(work)
    try:
        if _marker_row(dst) is not None:
            return work
        if not set(_TABLES) <= _tables(dst):
            raise NotAWorkCopy(
                "refused: not a copy of the source (rulebook tables missing)"
            )
        for table in _TABLES:
            if (
                src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                != dst.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            ):
                raise NotAWorkCopy(
                    f"refused: not a copy of the source ({table} differs)"
                )
        _write_marker(dst, _real(work), _real(source))
    finally:
        src.close()
        dst.close()
    return work
