"""Order 121 Part C: a stored file is found again after the data folder moves.

`documents.stored_path` and `reports.stored_path` held the writing machine's
absolute path. Copied to the owner's Mac, every page image of every document
answered 500 (pymupdf: no such file), with the file right there in the moved
folder. Paths under `data_dir` are now stored relative to it and resolved on
read; an old absolute path is found by its tail under this `data_dir`; and a
startup migration rewrites the old rows once.
"""

from __future__ import annotations

import shutil

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import db, stored_paths
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app


def _use(monkeypatch, data_dir):
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "upload_dir", data_dir / "uploads")
    monkeypatch.setattr(settings, "db_path", data_dir / "t.sqlite")
    db.reset_connection()


@pytest.fixture
def first_home(tmp_path, monkeypatch):
    home = tmp_path / "pc" / "data"
    home.mkdir(parents=True)
    _use(monkeypatch, home)
    db.init_db()
    yield home
    db.reset_connection()


def _upload(client, folder) -> str:
    path = folder / "sheet.pdf"
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 100), "Design pressure 10 barg")
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        doc_id = client.post(
            "/api/documents", files={"file": ("sheet.pdf", fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def _stored(doc_id: str) -> str:
    return (
        db.connect()
        .execute("SELECT stored_path FROM documents WHERE id = ?", (doc_id,))
        .fetchone()["stored_path"]
    )


def _move(home, tmp_path, monkeypatch):
    db.reset_connection()
    moved = tmp_path / "mac" / "data"
    moved.parent.mkdir(parents=True)
    shutil.move(str(home), str(moved))
    _use(monkeypatch, moved)
    return moved


def test_an_upload_stores_its_path_relative_to_the_data_folder(first_home):
    with TestClient(app) as client:
        doc_id = _upload(client, first_home)
    stored = _stored(doc_id)
    assert stored.startswith("uploads/") and stored.endswith(".pdf")
    assert (first_home / stored).is_file()


def test_a_page_still_opens_after_the_data_folder_moves(
    first_home, tmp_path, monkeypatch
):
    with TestClient(app) as client:
        doc_id = _upload(client, first_home)
    _move(first_home, tmp_path, monkeypatch)

    with TestClient(app) as client:
        r = client.get(f"/api/documents/{doc_id}/pages/1/image")

    assert r.status_code == 200, r.text
    assert r.content[:4] == b"\x89PNG"


def test_an_old_absolute_path_from_another_machine_still_opens_and_is_migrated(
    first_home, tmp_path, monkeypatch
):
    with TestClient(app) as client:
        doc_id = _upload(client, first_home)
    name = _stored(doc_id).rsplit("/", 1)[-1]
    windows = f"D:\\project\\app\\backend\\data\\uploads\\{name}"
    with db.connect() as conn:  # a row written before order 121 C, on the PC
        conn.execute(
            "UPDATE documents SET stored_path = ? WHERE id = ?", (windows, doc_id)
        )
    moved = _move(first_home, tmp_path, monkeypatch)

    assert stored_paths.local(windows) == str(moved / "uploads" / name)
    assert stored_paths.migrate() == {"rewritten": 1, "backup_path": None}
    assert _stored(doc_id) == f"uploads/{name}"
    assert stored_paths.migrate() == {"rewritten": 0, "backup_path": None}
    with TestClient(app) as client:
        assert client.get(f"/api/documents/{doc_id}/pages/1/image").status_code == 200


def test_the_migration_never_overwrites_a_path_written_after_it_read_the_row(
    first_home, monkeypatch
):
    with TestClient(app) as client:
        doc_id = _upload(client, first_home)
    old = str(first_home / _stored(doc_id))
    with db.connect() as conn:
        conn.execute("UPDATE documents SET stored_path = ? WHERE id = ?", (old, doc_id))
    real_pending = stored_paths._pending

    def read_then_a_writer_lands(conn):
        pending = real_pending(conn)
        conn.execute(
            "UPDATE documents SET stored_path = 'uploads/newer.pdf' WHERE id = ?",
            (doc_id,),
        )
        return pending

    monkeypatch.setattr(stored_paths, "_pending", read_then_a_writer_lands)

    assert stored_paths.migrate()["rewritten"] == 0
    assert _stored(doc_id) == "uploads/newer.pdf"


def test_a_path_outside_the_data_folder_stays_absolute_and_a_missing_file_stays_missing(
    first_home, tmp_path
):
    elsewhere = tmp_path / "elsewhere" / "x.pdf"
    assert stored_paths.to_stored(elsewhere) == str(elsewhere.resolve())
    gone = "D:\\nowhere\\uploads\\absent.pdf"
    assert stored_paths.local(gone) == gone
    assert stored_paths.local(None) is None
