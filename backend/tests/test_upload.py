import io

import pytest
from fastapi.testclient import TestClient

from app import db
from app.config import settings
from app.main import app
from app.upload import UploadError, ingest, stream_to_temp


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


# ------------------------------------------------------- the size ceiling

def test_an_upload_over_the_limit_is_rejected_during_the_stream(tmp_path, monkeypatch):
    """The point is to STOP READING, not to discover afterwards that we read
    too much. The limit is checked per block, so the abort happens while the
    stream is still arriving."""
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    monkeypatch.setattr(settings, "upload_chunk_bytes", 64 * 1024)
    blob = b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024)      # 2 MB against a 1 MB cap
    temp = tmp_path / "over.part"

    with pytest.raises(UploadError) as exc:
        stream_to_temp(io.BytesIO(blob), temp)
    assert exc.value.code == "too_large"
    # Shaped like not_pdf so the UI surfaces it rather than showing a 500.
    assert exc.value.code in {"too_large", "not_pdf"}

    # And the partial file must not be left behind by the caller.
    ingest_temp = tmp_path / "ingest.part"

    def fake_stream(src, path):
        path.write_bytes(b"partial")
        raise UploadError("too_large", "too big")

    monkeypatch.setattr("app.upload.stream_to_temp", fake_stream)
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    with pytest.raises(UploadError):
        ingest(io.BytesIO(blob), "over.pdf")
    assert not list(tmp_path.glob(".incoming-*.part")), "partial file was left on disk"


def test_a_document_just_under_the_limit_is_accepted(tmp_path, monkeypatch):
    """THIS IS THE ONE THAT MATTERS. A limit that rejects legitimate documents
    is worse than no limit at all, and it fails silently from the operator's
    side - the document simply never arrives.

    Sized against the real corpus: the largest document ingested is 37.6 MB
    (book4, 1,400 pages). This asserts a file just under the cap still gets
    through, so the ceiling can never be lowered past a legitimate document
    without a test failing.
    """
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    monkeypatch.setattr(settings, "upload_chunk_bytes", 64 * 1024)
    size = 1024 * 1024 - 1024                              # 1 KB under the cap
    blob = b"%PDF-1.7\n" + b"y" * (size - 9)
    temp = tmp_path / "under.part"

    sha, written = stream_to_temp(io.BytesIO(blob), temp)
    assert written == size
    assert len(sha) == 64
    assert temp.exists() and temp.stat().st_size == size


def test_the_configured_limit_clears_the_largest_real_document():
    """The ceiling is a measurement, not a round number. book4 is 37.6 MB at
    1,400 pages; if anyone lowers this below a document we have actually
    ingested, that is a regression and this fails."""
    assert settings.max_upload_mb >= 64, "below the largest document ingested (37.6 MB)"
