import io

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def pdf_bytes(body: bytes = b"x" * 5000) -> bytes:
    return b"%PDF-1.4\n" + body + b"\n%%EOF\n"


def test_upload_streams_hashes_and_records():
    c = TestClient(app)
    data = pdf_bytes()
    r = c.post("/api/documents", files={"file": ("spec.pdf", io.BytesIO(data), "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duplicate_of"] is None
    assert body["job_id"]
    doc = body["document"]
    assert doc["status"] == "queued"
    assert doc["size_bytes"] == len(data)
    # hash computed during the write pass must match an independent hash
    import hashlib
    assert doc["sha256"] == hashlib.sha256(data).hexdigest()


def test_duplicate_is_skipped_and_starts_no_job():
    c = TestClient(app)
    data = pdf_bytes()
    first = c.post("/api/documents", files={"file": ("a.pdf", io.BytesIO(data), "application/pdf")}).json()
    second = c.post("/api/documents", files={"file": ("renamed.pdf", io.BytesIO(data), "application/pdf")}).json()
    assert second["duplicate_of"] == first["document"]["id"]
    assert second["job_id"] == ""
    assert len(c.get("/api/documents").json()) == 1


def test_non_pdf_is_rejected_and_leaves_nothing_behind():
    c = TestClient(app)
    r = c.post("/api/documents", files={"file": ("evil.pdf", io.BytesIO(b"PK\x03\x04zip"), "application/zip")})
    assert r.status_code == 400
    assert r.json()["code"] == "not_pdf"
    assert c.get("/api/documents").json() == []
    assert list(settings.upload_dir.glob("*")) == []


def test_filename_is_sanitised():
    from app.upload import sanitise_filename
    assert sanitise_filename("../../etc/passwd") == "passwd.pdf"
    assert sanitise_filename(r"C:\secret\spec.pdf") == "spec.pdf"
    assert sanitise_filename("") == "document.pdf"
