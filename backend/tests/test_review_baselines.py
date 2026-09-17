from __future__ import annotations

import pytest

from app import db, review
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "review.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema()
    yield
    db.reset_connection()


def _doc(doc_id: str, name: str, digest: str):
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)
            VALUES (?,?,?,?,?,'ready',?)""",
            (doc_id, name, digest, 1, name, f"2026-09-17T00:00:0{len(doc_id)}Z"))


def _classification(doc_id: str, doc_type: str, discipline: str):
    with db.connect() as conn:
        conn.execute("""INSERT INTO document_classification
            (document_id,doc_type,discipline,doc_class,suggested_by)
            VALUES (?,?,?,?,?)""", (doc_id, doc_type, discipline, "SPECIFICATION", "test"))


def test_known_submittal_auto_selects_configured_baseline():
    _doc("submittal", "civil-submittal.pdf", "h1")
    _doc("baseline", "civil-requirements.pdf", "h2")
    _classification("submittal", "Drawing", "Civil")
    _classification("baseline", "Document", "Civil")
    rule = review.create_baseline_rule({
        "submittal_doc_type": "Drawing", "submittal_discipline": "Civil",
        "baseline_doc_type": "Document", "baseline_discipline": "Civil",
        "priority": 10, "active": True,
    })
    selected = review.resolve_baseline("submittal", allowed_document_ids=frozenset({"submittal", "baseline"}))
    assert selected == {"document_id": "baseline", "rule_id": rule["id"], "automatic": True}


def test_manual_baseline_override_wins_over_mapping():
    selected = review.resolve_baseline(
        "submittal", "manually-picked", allowed_document_ids=frozenset({"submittal", "manually-picked"}))
    assert selected == {"document_id": "manually-picked", "rule_id": None, "automatic": False}
