"""The ONE way anything other than the server writes to a live database.

WHY (owner decision, 2026-09-25, after the B3 incident): a maintenance script
run from a git worktree did not recognise the main checkout's live database
and wrote to it. A path check had been the only guard, and a path check is a
guess about which file is live. The owner's A5 rule is procedural - a verified
online backup and a restore drill BEFORE any live write - so the guard now
PERFORMS that procedure and refuses the write if any step fails.

TWO PARTS, both required:

1. `prepare_live_write(db_path, reason=...)` performs the A5 steps itself:
   an online backup (`scripts/backup_db.py`, the project's one backup tool),
   its integrity check, a table-by-table row-count comparison against the
   live file, and a restore drill - the backup restored into a disposable
   directory, integrity-checked again, compared again and proven writable.
   Only then is THIS PROCESS cleared to write THAT file. Any failure raises
   `LiveWriteRefused` and clears nothing.

2. `db.connect()` calls `check_connect(path)` before opening a connection. A
   live-shaped path is refused unless the process is the server (`run.py`
   marks it) or was cleared by step 1 for that exact file. So a script that
   forgets the helper FAILS instead of writing - the enforcement point is the
   connection every app code path goes through, not the script's own care.

"Live-shaped" = any `.../backend/data/rag_intelligence.sqlite`, in any
checkout. Read-only inspection needs no clearance: open the file with
`sqlite3.connect("file:...?mode=ro", uri=True)`, which cannot write.

The server marker is an environment variable, so a determined operator can
set it; this guards against ACCIDENTS, which is what happened, not against a
person deliberately bypassing it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

#: Set by `run.py` (and only there) for the server process.
SERVER_ENV = "RAG_LIVE_WRITER"
SERVER_VALUE = "server"

_cleared: dict[str, "LiveWriteClearance"] = {}


class LiveWriteRefused(RuntimeError):
    """A write to a live database without the A5 steps having passed."""


@dataclass(frozen=True)
class LiveWriteClearance:
    db_path: str
    reason: str
    backup_path: str
    tables_compared: int
    drill_ok: bool
    cleared_at: str
    manifest_path: str


def is_live_shaped(path: str | os.PathLike) -> bool:
    """Any checkout's live database, by the shape of its path."""
    p = Path(path).resolve()
    return (p.name == "rag_intelligence.sqlite" and p.parent.name == "data"
            and p.parent.parent.name == "backend")


def default_backup_dir(db_path: str | os.PathLike) -> Path:
    """`<checkout>-backups` beside the checkout the live file belongs to."""
    checkout = Path(db_path).resolve().parent.parent.parent
    return checkout.parent / f"{checkout.name}-backups"


def is_server_process() -> bool:
    return os.environ.get(SERVER_ENV) == SERVER_VALUE


def mark_server_process() -> None:
    """Called by `run.py` only: the running API is the live database's owner."""
    os.environ[SERVER_ENV] = SERVER_VALUE


def check_connect(path: str | os.PathLike) -> None:
    """Refuse a connection to a live database this process was not cleared for."""
    if not is_live_shaped(path) or is_server_process():
        return
    if str(Path(path).resolve()) in _cleared:
        return
    raise LiveWriteRefused(
        f"refusing to open the live database {path} for writing: this process "
        "is not the server and has not passed live_guard.prepare_live_write "
        "(verified backup + restore drill). Read-only inspection: open it with "
        "sqlite3 'file:...?mode=ro'.")


def _backup_tool():
    """`scripts/backup_db.py`, the project's one backup implementation."""
    here = Path(__file__).resolve()
    for root in here.parents:
        candidate = root / "scripts" / "backup_db.py"
        if candidate.is_file():
            spec = importlib.util.spec_from_file_location("backup_db", candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise LiveWriteRefused("scripts/backup_db.py not found; cannot take the backup")


def _counts(path: str | os.PathLike) -> dict[str, int]:
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                for (name,) in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name NOT LIKE 'sqlite_%'")}
    finally:
        conn.close()


def _restore_drill(backup_path: str, expected: dict[str, int]) -> None:
    """Restore the backup into a disposable directory and prove it usable."""
    scratch = Path(tempfile.mkdtemp(prefix="restore-drill-"))
    try:
        restored = scratch / "rag_intelligence.sqlite"
        shutil.copy2(backup_path, restored)
        conn = sqlite3.connect(restored)
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise LiveWriteRefused("restore drill: the restored copy fails integrity_check")
            conn.execute("CREATE TABLE restore_drill_probe (x INTEGER)")
            conn.execute("INSERT INTO restore_drill_probe VALUES (1)")
            conn.rollback()
        finally:
            conn.close()
        got = _counts(restored)
        got.pop("restore_drill_probe", None)
        if got != expected:
            raise LiveWriteRefused("restore drill: the restored copy's tables differ from the backup")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def prepare_live_write(db_path: str | os.PathLike, *, reason: str,
                       backup_dir: str | os.PathLike | None = None) -> LiveWriteClearance:
    """Perform the A5 steps, then clear this process to write `db_path`.

    Refuses (raises `LiveWriteRefused`) and clears nothing when: the path is
    not a live database (use it directly - no clearance is needed); the reason
    is empty; the backup, its integrity check, the live-vs-backup comparison
    or the restore drill fails. A live database being written to by the
    server during the comparison is a failure too - stop the writer or retry;
    a backup that does not match the file it claims to be is not a rollback
    point.
    """
    if not reason or not reason.strip():
        raise LiveWriteRefused("a live write needs a stated reason")
    live = Path(db_path).resolve()
    if not is_live_shaped(live):
        raise LiveWriteRefused(f"{live} is not a live database; no clearance applies")
    point = verified_rollback_point(live, backup_dir=backup_dir)

    now = datetime.now(UTC).isoformat(timespec="seconds")
    manifest = Path(f"{point['backup_path']}.clearance.json")
    manifest.write_text(json.dumps({
        "db_path": str(live), "reason": reason, **point, "cleared_at": now,
    }, indent=2), encoding="utf-8")
    clearance = LiveWriteClearance(
        db_path=str(live), reason=reason, backup_path=point["backup_path"],
        tables_compared=point["tables_compared"], drill_ok=True, cleared_at=now,
        manifest_path=str(manifest))
    _cleared[str(live)] = clearance
    return clearance


def diagnostic_copy(db_path: str | os.PathLike) -> Path:
    """A consistent, disposable copy of a live database for read-only work.

    The project's standing rule: diagnostics run on WAL-safe copies. Made
    with the backup API (the live file is opened read-only), into a fresh
    temporary directory whose path is NOT live-shaped, so `db.connect()`
    opens it freely and nothing can reach the live file through it.
    """
    scratch = Path(tempfile.mkdtemp(prefix="diagnostic-copy-"))
    path = _backup_tool().backup(str(Path(db_path).resolve()), str(scratch))
    return Path(path)


def clear_if_live(reason: str) -> LiveWriteClearance | None:
    """For a command about to write `settings.db_path`: the A5 steps first
    when that is a live database (and nothing when it is a copy or a test
    file). The one line every maintenance command path calls."""
    from .config import settings
    if is_live_shaped(settings.db_path) and not is_server_process():
        return prepare_live_write(settings.db_path, reason=reason)
    return None


def verified_rollback_point(db_path: str | os.PathLike, *,
                            backup_dir: str | os.PathLike | None = None) -> dict:
    """The A5 steps alone: backup, integrity, live comparison, restore drill.

    Reads the live file only (the backup tool opens it read-only). Returns
    what was proved; raises `LiveWriteRefused` on any failure. Clears nothing
    - `prepare_live_write` is the one caller that turns this into permission.
    """
    live = Path(db_path).resolve()
    target_dir = Path(backup_dir) if backup_dir else default_backup_dir(live)
    tool = _backup_tool()
    try:
        backup_path = tool.backup(str(live), str(target_dir))
        report = tool.verify(backup_path)
    except Exception as exc:  # noqa: BLE001 - every failure is a refusal
        raise LiveWriteRefused(f"backup step failed: {exc}") from exc
    if not report.get("ok"):
        raise LiveWriteRefused(f"backup failed integrity_check: {report.get('integrity')}")
    live_counts = _counts(live)
    if live_counts != report["tables"]:
        differ = sorted(t for t in set(live_counts) | set(report["tables"])
                        if live_counts.get(t) != report["tables"].get(t))
        raise LiveWriteRefused(
            f"the backup does not match the live file (tables differ: {differ[:5]}); "
            "stop whatever is writing and retry")
    _restore_drill(backup_path, report["tables"])
    return {"backup_path": backup_path, "integrity": report["integrity"],
            "tables_compared": len(live_counts), "rows_total": sum(live_counts.values()),
            "restore_drill": "ok",
            "verified_at": datetime.now(UTC).isoformat(timespec="seconds")}


def revoke_all() -> None:
    """Forget every clearance in this process (tests; end of a script)."""
    _cleared.clear()
