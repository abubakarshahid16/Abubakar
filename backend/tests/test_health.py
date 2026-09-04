"""Readiness, and the two contract facts it exists to prove.

These tests used a module-level TestClient and no storage fixture, so they ran
against whatever database happened to be on disk. On this machine that is a
real one left over from actual use, so they passed for weeks. On a clean CI
runner there is no database, nothing had created the schema, and /api/health
raised `no such table: documents`.

That is the same shape as everything else in the honesty audit: a test that
appeared to prove something while depending on ambient state it never set up.
It was invisible until CI ran the suite somewhere clean for the first time.
"""

import pytest
from fastapi.testclient import TestClient

from app import db, keyword
from app.config import settings
from app.main import app


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """Own the storage rather than borrowing whatever is lying around."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def test_health_ok():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_health_works_on_a_completely_empty_install():
    """A fresh machine must not 500 on the first request. This is the case
    that was never covered, because the developer machine is never fresh."""
    client = TestClient(app)
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert body["ingestion"]["pending_count"] == 0
    assert body["ingestion"]["documents_completed"] == 0


def test_embedding_model_is_staged():
    """The ONNX embedder must be on disk; nothing downloads at runtime."""
    assert (settings.embed_model_dir / "onnx" / "model_qint8_avx512_vnni.onnx").exists()


def test_binds_loopback_only():
    assert settings.host == "127.0.0.1"
