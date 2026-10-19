"""Order 129: the app starts even when no backup can be made.

#1151's startup migration asked `live_guard` for a verified backup before
rewriting old absolute stored paths. On a machine with no backup folder the
backup was refused, the refusal escaped `migrate()`, and the server stopped
with "Application startup failed". Now the rows are left as they are (`local`
still finds the files), the reason is logged in plain words, and startup goes
on.
"""

from __future__ import annotations

import logging
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, live_guard, stored_paths
from app.config import settings
from app.main import app

OLD = "D:\\project\\app\\backend\\data\\uploads\\sheet.pdf"


@pytest.fixture
def live_home_without_backups(tmp_path, monkeypatch):
    """A live-shaped database (`<checkout>/backend/data/rag_intelligence.sqlite`)
    holding a row from another machine, and no `<checkout>-backups` folder."""
    data = tmp_path / "checkout" / "backend" / "data"
    (data / "uploads").mkdir(parents=True)
    (data / "uploads" / "sheet.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(settings, "data_dir", data)
    monkeypatch.setattr(settings, "upload_dir", data / "uploads")
    monkeypatch.setattr(settings, "db_path", data / "rag_intelligence.sqlite")
    monkeypatch.setenv(live_guard.SERVER_ENV, live_guard.SERVER_VALUE)
    db.reset_connection()
    db.init_db()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
            " uploaded_at) VALUES ('d1', 'sheet.pdf', 'abc', 9, ?,"
            " '2026-10-19T00:00:00+00:00')",
            (OLD,),
        )
    assert live_guard.is_live_shaped(settings.db_path)
    assert not live_guard.default_backup_dir(settings.db_path).exists()
    yield data
    db.reset_connection()


def _stored() -> str:
    return (
        db.connect()
        .execute("SELECT stored_path FROM documents WHERE id = 'd1'")
        .fetchone()["stored_path"]
    )


def test_no_backup_leaves_the_rows_and_says_why(live_home_without_backups, caplog):
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = stored_paths.migrate()

    assert result["rewritten"] == 0 and result["backup_path"] is None
    assert result["skipped"]
    assert _stored() == OLD
    assert stored_paths.local(OLD) == str(
        live_home_without_backups / "uploads" / "sheet.pdf"
    )
    assert "no verified backup could be made" in caplog.text
    assert "The app starts normally" in caplog.text


def test_the_app_starts_without_a_backup_folder(live_home_without_backups):
    with TestClient(app) as client:
        r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert _stored() == OLD


def test_with_a_backup_folder_the_rows_are_still_rewritten(live_home_without_backups):
    backups = live_guard.default_backup_dir(settings.db_path)
    backups.mkdir()

    result = stored_paths.migrate()

    assert result["rewritten"] == 1 and "skipped" not in result
    assert result["backup_path"] and str(backups) in result["backup_path"]
    assert _stored() == "uploads/sheet.pdf"


def test_a_damaged_database_is_not_passed_off_as_a_missing_backup(
    live_home_without_backups, monkeypatch
):
    def malformed(_path):
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(live_guard, "verified_rollback_point", malformed)

    with pytest.raises(sqlite3.DatabaseError):
        stored_paths.migrate()


def test_a_failed_integrity_check_says_the_database_may_be_damaged(
    live_home_without_backups, monkeypatch, caplog
):
    def refused(_path):
        raise live_guard.LiveWriteRefused("backup failed integrity_check: corrupt")

    monkeypatch.setattr(live_guard, "verified_rollback_point", refused)

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        result = stored_paths.migrate()

    assert result["rewritten"] == 0 and _stored() == OLD
    assert any(
        r.levelno == logging.ERROR and "may be damaged" in r.getMessage()
        for r in caplog.records
    )
