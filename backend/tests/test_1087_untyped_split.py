"""#1087: the documents with no register type are split into "awaiting a type"
(no role: unknown) and "not in the register" (a role is set: the register types
only the deliverables it lists, so these are not waiting for one). Counts are
scoped to what the caller may read. Invented documents only.
"""

from __future__ import annotations

import pytest

from app import access, db, register_type_split
from app.config import settings
from app.db import connect

NOW = "2026-10-27T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _doc(doc_id: str, *, row: bool, doc_type=None, role=None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES (?,?,?,?,?,'ready',?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", 1, f"/tmp/{doc_id}", NOW),
        )
        if row:
            conn.execute(
                "INSERT INTO document_classification (document_id,doc_type,"
                "document_role,suggested_by) VALUES (?,?,?,'none')",
                (doc_id, doc_type, role),
            )


def _scope(*ids: str) -> access.AccessScope:
    return access.AccessScope(user_id="u", allowed_document_ids=frozenset(ids))


def test_a_role_with_no_type_is_not_in_the_register_and_no_role_is_awaiting():
    _doc("standard", row=True, role="COMPANY_STANDARD")
    _doc("submittal", row=True, role="CONTRACTOR_SUBMITTAL")
    _doc("no_role", row=True)
    _doc("no_row", row=False)
    _doc("typed", row=True, doc_type="Drawing", role="CONTRACT_DOCUMENT")
    scope = _scope("standard", "submittal", "no_role", "no_row", "typed")
    assert register_type_split.untyped_split(scope) == (2, 2)


def test_the_two_counts_add_up_to_the_untyped_documents():
    _doc("a", row=True, role="CRS_TEMPLATE")
    _doc("b", row=True)
    _doc("c", row=True, doc_type="Document")
    awaiting, not_in_register = register_type_split.untyped_split(_scope("a", "b", "c"))
    assert awaiting + not_in_register == 2


def test_it_counts_only_what_the_caller_may_read():
    _doc("mine", row=True, role="COMPANY_STANDARD")
    _doc("theirs", row=True, role="COMPANY_STANDARD")
    assert register_type_split.untyped_split(_scope("mine")) == (0, 1)
    assert register_type_split.untyped_split(_scope()) == (0, 0)


def test_the_vocabulary_route_carries_the_split():
    from fastapi.testclient import TestClient

    from app.main import app

    _doc("standard", row=True, role="COMPANY_STANDARD")
    _doc("no_role", row=True)
    body = (
        TestClient(app, base_url="http://localhost")
        .get("/api/classification/vocabulary")
        .json()
    )
    assert (body["awaiting_type"], body["not_in_register"]) == (1, 1)
    # needs_classification (no CONFIRMED classification) is a different set and stays.
    assert body["needs_classification"] == 2
