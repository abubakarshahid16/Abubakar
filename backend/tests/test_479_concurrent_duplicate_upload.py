"""#479 item 2: two uploads of the same file at the same moment.

WHAT WAS WRONG. Both uploads passed `find_by_hash` before either had written
its row; the second INSERT then hit `documents.sha256 UNIQUE`, nothing caught
the IntegrityError, and the second uploader got a 500.

The race is made deterministic here: the second upload's FIRST hash lookup
answers "not seen yet", which is what it saw while the first upload was still
between its own lookup and its INSERT.
"""
from __future__ import annotations

import hashlib
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db, upload
from app.main import app
from tests.test_upload import pdf_bytes, temp_storage  # noqa: F401 - autouse fixture


def _lost_the_race(monkeypatch):
    """The next `find_by_hash` call answers None once, then the truth."""
    real = upload.find_by_hash
    calls = {"n": 0}

    def lookup(sha256):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(sha256)

    monkeypatch.setattr(upload, "find_by_hash", lookup)
    return calls


def test_the_upload_that_loses_the_race_is_a_duplicate_not_a_500(monkeypatch):
    client = TestClient(app, raise_server_exceptions=False)
    data = pdf_bytes()
    first = client.post("/api/documents",
                        files={"file": ("a.pdf", io.BytesIO(data), "application/pdf")})
    assert first.status_code == 200, first.text
    first_id = first.json()["document"]["id"]

    calls = _lost_the_race(monkeypatch)
    second = client.post("/api/documents",
                         files={"file": ("b.pdf", io.BytesIO(data), "application/pdf")})

    assert calls["n"] >= 1, "the race was not staged; the check below would be vacuous"
    assert second.status_code == 200, second.text
    body = second.json()
    # the answer a duplicate uploaded a moment later gets
    assert body["duplicate_of"] == first_id
    assert body["job_id"] == ""
    assert body["document"]["id"] == first_id
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_a_constraint_that_is_not_a_duplicate_still_raises(monkeypatch):
    """Same `doc_<12 hex>` id, different hash: not the same file, so it must
    not be answered as a duplicate of anything."""
    data = pdf_bytes(b"y" * 5000)
    sha = hashlib.sha256(data).hexdigest()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
            " VALUES (?, 'other.pdf', 'not-this-hash', 1, 'x', 'ready', '2020-01-01')",
            (f"doc_{sha[:12]}",))
    with pytest.raises(sqlite3.IntegrityError):
        upload.ingest(io.BytesIO(data), "c.pdf")
