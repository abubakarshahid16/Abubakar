"""W7: the Documents page makes ONE request. `GET /api/documents` carries each
document's classification, under exactly the scope the list already had.
Mutations M2901-M2905."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, classification as classification_mod, db
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-05T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w7.sqlite")
    db.reset_connection(); db.init_db()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(doc_id, *, doc_type=None, subject=None):
    conn = connect()
    with conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,?,?,1,?,'ready',1,?)""",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW))
        if doc_type is not None:
            conn.execute("""INSERT INTO document_classification
                (document_id,suggested_by,doc_type,discipline,document_role)
                VALUES (?,?,?,?,?)""",
                (doc_id, "pattern", doc_type, "Mechanical", "COMPANY_STANDARD"))
        if subject:
            conn.execute("INSERT OR IGNORE INTO subjects (id,name,kind,register_revision)"
                         " VALUES (?,?,?,?)", (f"s-{subject}", subject, "system", "r1"))
            conn.execute("""INSERT INTO document_subjects
                (document_id,subject_id,suggested_by) VALUES (?,?,?)""",
                (doc_id, f"s-{subject}", "pattern"))


def _grant(user_id, document_ids):
    conn = connect()
    with conn:
        conn.execute("INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
                     "created_at) VALUES (?,?,?,?,?)",
                     (user_id, f"{user_id}@x", user_id, "h", NOW))
        rid = f"role_{user_id}"
        conn.execute("INSERT OR IGNORE INTO roles (id,name,description,created_at)"
                     " VALUES (?,?,?,?)", (rid, rid, rid, NOW))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,granted_at)"
                     " VALUES (?,?,?)", (user_id, rid, NOW))
        for d in document_ids:
            conn.execute("INSERT OR IGNORE INTO document_role_access (document_id,"
                         "role_id,permission,granted_at) VALUES (?,?,'read',?)",
                         (d, rid, NOW))


def test_the_list_carries_each_documents_classification_identical_to_the_single_route():
    _doc("a", doc_type="Datasheet", subject="pump")
    _doc("b", doc_type="Specification")
    client = TestClient(app)
    listed = {d["id"]: d for d in client.get("/api/documents").json()}
    assert set(listed) == {"a", "b"}
    for doc_id in ("a", "b"):
        single = client.get(f"/api/documents/{doc_id}/classification").json()
        assert listed[doc_id]["classification"] == single
    assert listed["a"]["classification"]["doc_type"] == "Datasheet"
    assert [s["name"] for s in listed["a"]["classification"]["subjects"]] == ["pump"]


def test_a_document_never_classified_gets_the_same_empty_record_as_the_single_route():
    _doc("plain")
    client = TestClient(app)
    [doc] = client.get("/api/documents").json()
    assert doc["classification"] == client.get(
        "/api/documents/plain/classification").json()
    assert doc["classification"]["doc_type"] is None
    assert doc["classification"]["confirmed"] is False


def test_a_caller_gets_the_classification_of_only_the_documents_they_may_read(monkeypatch):
    """The scope is the list's, untouched: a hidden document is absent, and so
    is everything about it (its type, its subject)."""
    _doc("visible", doc_type="Datasheet")
    _doc("hidden", doc_type="SecretType", subject="secret-subject")
    _grant("u1", ["visible"])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: "u1")
    client = TestClient(app)
    response = client.get("/api/documents")
    body = response.json()
    assert [d["id"] for d in body] == ["visible"]            # positive first
    assert body[0]["classification"]["doc_type"] == "Datasheet"
    assert "hidden" not in response.text
    assert "SecretType" not in response.text and "secret-subject" not in response.text


def test_many_documents_cost_a_fixed_number_of_classification_queries():
    for i in range(30):
        _doc(f"d{i:02d}", doc_type="Datasheet", subject="pump")
    statements: list[str] = []
    conn = connect()
    conn.set_trace_callback(statements.append)
    try:
        result = classification_mod.of_documents([f"d{i:02d}" for i in range(30)])
    finally:
        conn.set_trace_callback(None)
    assert len(result) == 30                                  # positive first
    assert len([s for s in statements if "document_classification" in s
                or "document_subjects" in s]) <= 2


def test_of_document_and_of_documents_agree():
    _doc("a", doc_type="Datasheet", subject="pump")
    assert classification_mod.of_document("a") == classification_mod.of_documents(["a"])["a"]
    assert classification_mod.of_document("missing") is None
