"""The live-write guard (owner decision 2026-09-25, after the B3 incident).

A maintenance script run from a git worktree did not recognise the main
checkout's live database and wrote to it; a path check had been the only
guard. The owner's rule: every script or command path that can write to the
live database goes through ONE helper that PERFORMS the A5 steps - verified
online backup, restore drill - before writing, and refuses otherwise.

Proved here against real SQLite files laid out like a checkout
(`<root>/<checkout>/backend/data/rag_intelligence.sqlite`, backups in
`<root>/<checkout>-backups`):

  - `db.connect()` refuses a live-shaped database from a process that is
    neither the server nor cleared - nothing is created or written;
  - `prepare_live_write` takes the backup, compares every table, runs the
    restore drill, writes a clearance manifest, and only then allows it;
  - it refuses, and clears nothing, when the backup cannot be taken, when the
    backup does not match the live file, when the restore drill fails, or
    when no reason is given;
  - the server process (marked by run.py) is allowed; run.py marks it;
  - the backfill and resetdoc commands go through it; and no script in
    scripts/ opens a raw read-write connection outside it.

Mutations: M466-M471, `python scripts/mutation_check.py --only M466 M467 M468 M469 M470 M471`.
"""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app import db, live_guard
from app.config import settings

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv(live_guard.SERVER_ENV, raising=False)
    live_guard.revoke_all()
    db.reset_connection()
    yield
    live_guard.revoke_all()
    db.reset_connection()


def _live(tmp_path, *, backups=True, rows=3) -> Path:
    """A real live-shaped database with data, beside its backups folder."""
    live = tmp_path / "checkout" / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    conn = sqlite3.connect(live)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE documents (id TEXT PRIMARY KEY)")
    conn.executemany("INSERT INTO documents VALUES (?)", [(f"d{i}",) for i in range(rows)])
    conn.commit()
    conn.close()
    if backups:
        (tmp_path / "checkout-backups").mkdir()
    return live


def _rows(path: Path) -> int:
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        conn.close()


# ================================================= the connection-layer refusal

def test_a_live_database_is_refused_without_a_verified_backup(tmp_path, monkeypatch):
    live = _live(tmp_path)
    monkeypatch.setattr(settings, "db_path", live)

    with pytest.raises(live_guard.LiveWriteRefused, match="prepare_live_write"):
        db.connect()

    assert _rows(live) == 3
    assert not list((tmp_path / "checkout-backups").iterdir()), "a refusal took a backup"


def test_a_database_that_is_not_live_opens_freely(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "copy.sqlite")
    assert db.connect() is not None


def test_the_server_process_may_open_the_live_database(tmp_path, monkeypatch):
    live = _live(tmp_path)
    monkeypatch.setattr(settings, "db_path", live)
    monkeypatch.setenv(live_guard.SERVER_ENV, live_guard.SERVER_VALUE)
    assert db.connect() is not None


def test_run_py_marks_the_server_before_it_starts(monkeypatch):
    sys.path.insert(0, str(REPO / "backend"))
    import run  # noqa: PLC0415
    seen = {}
    monkeypatch.setattr(run.uvicorn, "run",
                        lambda *a, **k: seen.update(env=live_guard.is_server_process()))
    run.main()
    assert seen["env"] is True, "the server would be refused its own database"


# ======================================================= the A5 steps, performed

def test_clearance_takes_a_verified_backup_and_drill_first(tmp_path, monkeypatch):
    live = _live(tmp_path)

    clearance = live_guard.prepare_live_write(live, reason="test write")

    backup = Path(clearance.backup_path)
    assert backup.parent == tmp_path / "checkout-backups"
    assert _rows(backup) == 3, "the backup does not hold the live rows"
    manifest = json.loads(Path(clearance.manifest_path).read_text(encoding="utf-8"))
    assert manifest["restore_drill"] == "ok"
    assert manifest["integrity"] == "ok"
    assert manifest["tables_compared"] == 1
    assert manifest["reason"] == "test write"
    monkeypatch.setattr(settings, "db_path", live)
    with db.connect() as conn:
        conn.execute("INSERT INTO documents VALUES ('new')")
    assert _rows(live) == 4


def test_no_backup_folder_means_no_clearance(tmp_path, monkeypatch):
    live = _live(tmp_path, backups=False)

    with pytest.raises(live_guard.LiveWriteRefused, match="backup step failed"):
        live_guard.prepare_live_write(live, reason="test")

    monkeypatch.setattr(settings, "db_path", live)
    with pytest.raises(live_guard.LiveWriteRefused):
        db.connect()


def test_a_backup_that_does_not_match_the_live_file_is_refused(tmp_path, monkeypatch):
    live = _live(tmp_path)
    real = live_guard._counts
    monkeypatch.setattr(live_guard, "_counts",
                        lambda p: {**real(p), "documents": 999} if Path(p) == live.resolve()
                        else real(p))

    with pytest.raises(live_guard.LiveWriteRefused, match="does not match the live file"):
        live_guard.prepare_live_write(live, reason="test")
    assert str(live.resolve()) not in live_guard._cleared


def test_a_failed_restore_drill_is_refused(tmp_path, monkeypatch):
    live = _live(tmp_path)
    real_copy = live_guard.shutil.copy2

    def corrupt(src, dst, *a, **k):
        real_copy(src, dst, *a, **k)
        Path(dst).write_bytes(b"not a database")
    monkeypatch.setattr(live_guard.shutil, "copy2", corrupt)

    with pytest.raises((live_guard.LiveWriteRefused, sqlite3.DatabaseError)):
        live_guard.prepare_live_write(live, reason="test")
    assert str(live.resolve()) not in live_guard._cleared


def test_a_live_write_needs_a_reason(tmp_path):
    with pytest.raises(live_guard.LiveWriteRefused, match="reason"):
        live_guard.prepare_live_write(_live(tmp_path), reason="  ")


# ======================================================== the command paths

def _script(name: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO / "scripts" / name), *args],
                          capture_output=True, text=True, timeout=180, cwd=REPO)


def test_the_backfill_refuses_a_live_database_without_the_flag(tmp_path):
    live = _live(tmp_path)
    result = _script("backfill_page_ledger.py", "--db", str(live))
    assert result.returncode != 0 and "refusing" in result.stderr
    assert not list((tmp_path / "checkout-backups").iterdir())


def test_the_backfill_with_live_but_no_verified_backup_is_refused(tmp_path):
    live = _live(tmp_path)
    result = _script("backfill_page_ledger.py", "--db", str(live), "--live",
                     "--backup-dir", str(tmp_path / "no-such-dir"))
    assert result.returncode != 0
    assert "LiveWriteRefused" in result.stderr and "backup step failed" in result.stderr
    conn = sqlite3.connect(f"{live.as_uri()}?mode=ro", uri=True)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "page_ledger" not in tables, "the refused backfill wrote the live database"


def test_resetdoc_takes_the_rollback_point_before_it_writes(tmp_path):
    live = _live(tmp_path)
    conn = sqlite3.connect(live)
    conn.executescript("""CREATE TABLE pages (document_id TEXT);
        INSERT INTO pages VALUES ('d1');
        CREATE TABLE jobs (document_id TEXT, state TEXT, stage TEXT, pages_done INT,
                           last_completed_batch INT, pages_total INT);""")
    conn.execute("ALTER TABLE documents ADD COLUMN pages_done INT")
    conn.execute("ALTER TABLE documents ADD COLUMN needs_ocr_pages INT")
    conn.execute("ALTER TABLE documents ADD COLUMN page_count INT")
    conn.execute("ALTER TABLE documents ADD COLUMN status TEXT")
    conn.commit()
    conn.close()

    result = _script("resetdoc.py", "d1", "--db", str(live))

    assert result.returncode == 0, result.stderr
    [backup] = [p for p in (tmp_path / "checkout-backups").glob("*.sqlite")]
    assert "rollback point" in result.stdout
    check = sqlite3.connect(f"{backup.as_uri()}?mode=ro", uri=True)
    assert check.execute("SELECT COUNT(*) FROM pages").fetchone()[0] == 1, \
        "the backup was taken after the write"
    check.close()


def test_resetdoc_refuses_when_no_rollback_point_can_be_taken(tmp_path):
    live = _live(tmp_path, backups=False)
    result = _script("resetdoc.py", "d1", "--db", str(live))
    assert result.returncode != 0
    assert "LiveWriteRefused" in result.stderr


#: Scripts that open a raw READ-WRITE sqlite connection without the guard,
#: each with the reason it cannot reach the live file. Adding a name here is
#: a decision someone must be able to read.
RAW_WRITERS_ALLOWED = {
    "backup_db.py": "writes only the backup file it has just created exclusively",
    "reader_score_standard.py": "writes only its own backup-API copy",
    "mutation_check.py": "the matches are mutation anchor strings, not connections",
}


def test_no_script_opens_a_raw_read_write_connection_outside_the_guard():
    offenders = []
    for path in sorted((REPO / "scripts").glob("*.py")):
        if path.name in RAW_WRITERS_ALLOWED:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        uses_guard = "live_guard.prepare_live_write" in "\n".join(lines)
        for i, line in enumerate(lines):
            if not re.search(r"sqlite3\.connect\(", line):
                continue
            window = "\n".join(lines[max(0, i - 2):i + 1])
            if "mode=ro" in window or uses_guard:
                continue
            offenders.append(f"{path.name}:{i + 1}")
    assert offenders == [], f"raw read-write connections outside live_guard: {offenders}"
