"""Order 121 Part C: a stored file's path, written relative to `data_dir`.

`documents.stored_path` and `reports.stored_path` held the ABSOLUTE path of the
machine that wrote them (`D:\\project\\app\\backend\\data\\uploads\\<sha>.pdf`).
Moved to another machine, every page image, highlight and download of every
document failed with "file not found", though the file was right there in the
moved data folder.

So a path under `data_dir` is stored relative to it (`uploads/<sha>.pdf`), and
turned into this machine's path when it is read (`local`). A path outside
`data_dir` (an `upload_dir` set elsewhere) cannot be relative and stays
absolute. `local` also finds the file behind an absolute path written on
another machine, by its tail under this `data_dir`, so a database not yet
migrated still opens; `migrate` rewrites those rows once, at startup, after a
verified backup when the database is a live one.
"""

from __future__ import annotations

import logging
from pathlib import Path, PurePosixPath, PureWindowsPath

from .config import settings


def _parts(value: str) -> tuple[bool, tuple[str, ...]]:
    """(absolute?, parts) of a stored path, whichever machine wrote it."""
    if "\\" in value or (len(value) > 1 and value[1] == ":"):
        win = PureWindowsPath(value)
        return bool(win.drive or win.root), win.parts[1:] if win.anchor else win.parts
    posix = PurePosixPath(value)
    return posix.is_absolute(), posix.parts[1:] if posix.is_absolute() else posix.parts


def to_stored(path: str | Path) -> str:
    """What to write in a `stored_path` column for a file at `path`."""
    absolute = Path(path).resolve()
    try:
        return absolute.relative_to(settings.data_dir.resolve()).as_posix()
    except ValueError:
        return str(absolute)


def local(value: str | None) -> str | None:
    """This machine's path for a stored value; the value itself when nothing
    on this machine matches, so a missing file stays a missing file."""
    if not value:
        return value
    absolute, parts = _parts(value)
    if not absolute:
        return str(settings.data_dir.joinpath(*parts))
    if Path(value).exists():
        return value
    # Written on another machine: the longest tail of it that exists here.
    for start in range(len(parts)):
        candidate = settings.data_dir.joinpath(*parts[start:])
        if candidate.is_file():
            return str(candidate)
    return value


def of_document(document_id: str) -> str | None:
    """This machine's path of a document's stored file; None when there is none."""
    from .db import connect

    row = (
        connect()
        .execute("SELECT stored_path FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    return local(row["stored_path"]) if row else None


def _pending(conn) -> list[tuple[str, str, str, str]]:
    """(table, id, stored value, value to store) for every row still holding
    an absolute path to a file under `data_dir`."""
    out = []
    for table in ("documents", "reports"):
        for row in conn.execute(
            f"SELECT id, stored_path FROM {table} WHERE stored_path IS NOT NULL"
        ):
            value = row["stored_path"]
            if not _parts(value)[0]:
                continue
            found = local(value)
            if not found or not Path(found).is_file():
                continue
            stored = to_stored(found)
            if stored != value and not _parts(stored)[0]:
                out.append((table, row["id"], value, stored))
    return out


def migrate() -> dict:
    """Rewrite the absolute paths under `data_dir` as relative ones, once
    (`main._init_db`, at every start, before anything reads them).

    A live database is backed up and the backup proved first (the A5 steps).
    Each row is changed only while it still holds the value read, so a path
    written meanwhile is never overwritten (as #1137). Run again, it finds
    nothing to do.

    No verified backup (no backup folder, a failed check): the rows are left
    as they are and the app starts (order 129). `local` already finds a file
    behind an old absolute path, so nothing is lost; the next start tries
    again. It once stopped the app from starting at all (#1151)."""
    from . import live_guard
    from .db import connect

    conn = connect()
    pending = _pending(conn)
    if not pending:
        return {"rewritten": 0, "backup_path": None}
    log = logging.getLogger("uvicorn.error")
    backup = None
    if live_guard.is_live_shaped(settings.db_path):
        try:
            backup = live_guard.verified_rollback_point(settings.db_path)["backup_path"]
        except live_guard.LiveWriteRefused as exc:
            # Only a refusal: anything else (a malformed database) is not a
            # missing backup and must not be passed off as one.
            log.warning(
                "Stored file paths were left as they are: no verified backup "
                "could be made (%s). Files are still found by their old paths. "
                "The app starts normally; the next start tries again.",
                exc,
            )
            if "integrity" in str(exc):
                log.error(
                    "The database backup failed its integrity check. The "
                    "database itself may be damaged: copy the whole data "
                    "folder and check that copy before relying on it."
                )
            return {"rewritten": 0, "backup_path": None, "skipped": str(exc)}
    rewritten = 0
    with conn:
        for table, row_id, value, stored in pending:
            rewritten += conn.execute(
                f"UPDATE {table} SET stored_path = ? WHERE id = ? AND stored_path = ?",
                (stored, row_id, value),
            ).rowcount
    log.warning(
        "stored paths made relative to data_dir: %d rows (backup: %s)",
        rewritten,
        backup,
    )
    return {"rewritten": rewritten, "backup_path": backup}
