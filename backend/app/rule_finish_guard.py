"""Where the rule finishing line may write: only a COPY made by `prepare_work_copy`, found by a positive marker.

A database is writable by the finishing line only when it carries the table `rule_finish_work_marker` with a row that
names THIS file (its own resolved path) and the source it was copied from, and when its resolved path is none of the
protected databases (the compile source, the pages database, the app's database, the live database). Every write
function calls `require_work_copy`. The marker is created only by `prepare_work_copy` (a new copy) or `adopt_copy` (an
earlier copy, verified to hold the same rulebook tables as its source). A file-name deny list is not used: a copy renamed
to anything is still checked by what it is, not by what it is called.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .config import settings

MARKER = "rule_finish_work_marker"
_TABLES = ("rulebook_rule", "rulebook_version", "rulebook_provenance")
HOME = Path.home()
#: Databases that are never written, whatever a caller passes: the compile source and the standards' pages copy.
DEFAULT_SOURCE = HOME / "project/mirror/proof/db/compile/psv-all.sqlite"
DEFAULT_PAGES = HOME / "project/mirror/proof/agent-test/db/agent-copy.sqlite"
DEFAULT_KEY_FILE = HOME / "project/mirror/trace/.rule-finish-marker-key"
_REGISTERED: list[str] = []


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


def register_protected(path: str | os.PathLike) -> None:
    """A path a caller told us is a source or a pages database: protected from now on in this process."""
    if str(path) not in _REGISTERED:
        _REGISTERED.append(str(path))


def protected_paths(extra: list[str | os.PathLike] | None = None) -> list[str]:
    """EVERY protected database, computed here whatever the caller passes: the source and pages defaults, every path
    registered as a source or pages database, the app's database, the live one, and `extra`."""
    found = [
        str(DEFAULT_SOURCE),
        str(DEFAULT_PAGES),
        *_REGISTERED,
        str(settings.db_path),
        *map(str, extra or ()),
    ]
    live = os.environ.get("DB_PATH")
    if live:
        found.append(live)
    return found


def db_file(conn: sqlite3.Connection) -> str:
    for _, name, path in conn.execute("PRAGMA database_list"):
        if name == "main":
            return path or ""
    return ""


def _key() -> bytes:
    path = Path(os.environ.get("RULE_FINISH_MARKER_KEY_FILE") or DEFAULT_KEY_FILE)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(uuid.uuid4().hex + uuid.uuid4().hex)
    return path.read_text().strip().encode()


def _mac(
    marker_id: str, copy_path: str, source_path: str, created_at: str, rows: str
) -> str:
    return hmac.new(
        _key(),
        "|".join((marker_id, copy_path, source_path, created_at, rows)).encode(),
        hashlib.sha256,
    ).hexdigest()


def _counts(conn: sqlite3.Connection) -> str | None:
    try:
        return json.dumps(
            {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in _TABLES
            }
        )
    except sqlite3.OperationalError:
        return None


def _marker_row(conn: sqlite3.Connection):
    try:
        return conn.execute(
            f"SELECT marker_id, copy_path, source_path, created_at, rows_json, mac FROM {MARKER} LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None


def require_work_copy(
    conn: sqlite3.Connection, protected: list[str | os.PathLike] | None = None
) -> str:
    """Return the marker id, or raise NotAWorkCopy. Called by EVERY write function. A marker alone is never enough: its
    keyed signature must verify, it must name THIS file, the file must still hold the rulebook tables the copy was made
    with, and the file must be none of the protected databases (computed here, not taken from the caller)."""
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
    if not hmac.compare_digest(row[5], _mac(*row[:5])):
        raise NotAWorkCopy("refused: the marker is not signed by this tool")
    if row[1] != _real(path):
        raise NotAWorkCopy(
            "refused: the marker names another file; this is not the copy it was made for"
        )
    if _counts(conn) != row[4]:
        raise NotAWorkCopy(
            "refused: the file no longer holds the rulebook tables the copy was made with"
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
    conn.execute(f"DROP TABLE IF EXISTS {MARKER}")
    conn.execute(
        f"CREATE TABLE {MARKER} (marker_id TEXT PRIMARY KEY, copy_path TEXT NOT NULL, source_path TEXT NOT NULL, "
        "created_at TEXT NOT NULL, rows_json TEXT NOT NULL, mac TEXT NOT NULL)"
    )
    marker_id, created = (
        uuid.uuid4().hex,
        datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    rows = _counts(conn) or "{}"
    conn.execute(
        f"INSERT INTO {MARKER} VALUES (?,?,?,?,?,?)",
        (
            marker_id,
            copy_path,
            source_path,
            created,
            rows,
            _mac(marker_id, copy_path, source_path, created, rows),
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
    """The copy the finishing line writes to. Refuses a protected database (the source first) as the target; makes a new
    copy of `source` and marks it; an existing target must already be marked for itself (else use `adopt_copy`)."""
    register_protected(source)
    _refuse_protected(work, [source, *(protected or ())])
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
        require_work_copy(conn, [source, *(protected or ())])
    finally:
        conn.close()
    return work


def adopt_copy(
    source: Path, work: Path, protected: list[str | os.PathLike] | None = None
) -> Path:
    """Mark an EXISTING file as a work copy, once, when it is verified to be a copy of `source`: not the same file, and
    the same rulebook tables with the same row counts. An older or invalid marker is replaced by a valid one."""
    register_protected(source)
    _refuse_protected(work, [source, *(protected or ())])
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(work)
    try:
        if not set(_TABLES) <= _tables(dst):
            raise NotAWorkCopy(
                "refused: not a copy of the source (rulebook tables missing)"
            )
        if _counts(src) != _counts(dst):
            raise NotAWorkCopy(
                "refused: not a copy of the source (the rulebook tables differ)"
            )
        try:
            require_work_copy(dst, [source, *(protected or ())])
            return work
        except NotAWorkCopy:
            pass
        _write_marker(dst, _real(work), _real(source))
    finally:
        src.close()
        dst.close()
    return work
