"""B9: reopening a conversation obeys the caller's grants AT READ TIME.

A stored assistant turn is a copy of document text taken when the question
was asked. Before this fix, `GET /api/conversations/{id}` returned every stored
payload unchanged, so a grant revoked after the question still leaked the
cited passage - and the answer prose that quotes it - to the same user on
reopen. Ownership (test_conversations_ownership.py) answers "whose
conversation"; this file answers "which of its turns may they still see".
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import access, chat, db
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-26T00:00:00Z"
KEPT_QUOTE = "Flanges shall be raised face ZQK-KEPT"
REVOKED_QUOTE = "Bolts shall be galvanised ZQK-GONE"
REVOKED_NAME = "revoked-standard-ZQK.pdf"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(conn, doc_id: str, name: str) -> None:
    conn.execute(
        "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,"
        " uploaded_at, status) VALUES (?,?,?,?,?,?,?)",
        (doc_id, name, doc_id * 4, 1, f"/x/{doc_id}", NOW, "indexed"))
    conn.execute("INSERT INTO document_role_access (document_id, role_id, granted_at)"
                 " VALUES (?,?,?)", (doc_id, "role_u", NOW))


def _answer(conn, cid, ordinal, mid, text, doc_id, name):
    payload = {"passage": {"chunk_id": f"c_{doc_id}", "document_id": doc_id,
                           "filename": name, "page": 3, "text": text}}
    conn.execute(
        "INSERT INTO messages (id, conversation_id, ordinal, role, text, payload,"
        " created_at) VALUES (?,?,?,?,?,?,?)",
        (mid, cid, ordinal, "assistant", text, json.dumps(payload), NOW))


@pytest.fixture
def conversation():
    conn = connect()
    with conn:
        conn.execute("INSERT INTO users (id, email, display_name, password_hash,"
                     " created_at) VALUES (?,?,?,?,?)", ("user_u", "u@x", "u", "h", NOW))
        conn.execute("INSERT INTO roles (id, name, description, kind, created_at)"
                     " VALUES (?,?,?,?,?)", ("role_u", "role_u", "r", "discipline", NOW))
        conn.execute("INSERT INTO user_roles (user_id, role_id, granted_at)"
                     " VALUES (?,?,?)", ("user_u", "role_u", NOW))
        _doc(conn, "doc_kept", "kept.pdf")
        _doc(conn, "doc_gone", REVOKED_NAME)
    access.set_user_resolver(lambda req: "user_u")
    client = TestClient(app)
    r = client.post("/api/conversations", json={"title": "flanges and bolts"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    with conn:
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " created_at) VALUES (?,?,?,?,?,?)",
                     ("m1", cid, 1, "user", "what about flanges", NOW))
        _answer(conn, cid, 2, "m2", KEPT_QUOTE, "doc_kept", "kept.pdf")
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " created_at) VALUES (?,?,?,?,?,?)",
                     ("m3", cid, 3, "user", "and bolts", NOW))
        _answer(conn, cid, 4, "m4", REVOKED_QUOTE, "doc_gone", REVOKED_NAME)
    return client, cid


def test_before_revocation_both_answers_reopen_intact(conversation):
    """The control: the filter hides nothing the caller may still read."""
    client, cid = conversation
    body = client.get(f"/api/conversations/{cid}").text
    assert KEPT_QUOTE in body and REVOKED_QUOTE in body


def test_a_revoked_grant_withholds_the_answer_that_cited_it(conversation):
    client, cid = conversation
    with connect() as conn:
        conn.execute("DELETE FROM document_role_access WHERE document_id = 'doc_gone'")
    r = client.get(f"/api/conversations/{cid}")
    assert r.status_code == 200
    body = r.text
    for leaked in (REVOKED_QUOTE, REVOKED_NAME, "doc_gone"):
        assert leaked not in body, f"revoked document content reached the body: {leaked!r}"
    messages = {m["id"]: m for m in r.json()["messages"]}
    assert messages["m4"]["text"] == chat.WITHHELD_TEXT
    assert messages["m4"]["payload"] == {"withheld": True}
    # The rest of the conversation still reads: withholding is per turn.
    assert messages["m2"]["text"] == KEPT_QUOTE
    assert messages["m2"]["payload"]["passage"]["document_id"] == "doc_kept"
    # The user's own typed question is theirs and stays.
    assert messages["m3"]["text"] == "and bolts"


def test_ids_are_found_at_any_depth_and_in_id_lists():
    payload = {
        "coverage": {"rows": [{"document_id": "d1"}]},
        "understanding": {"scope_ids": ["d2", "d3"], "document_id": None},
        "near_duplicates": [{"chunk_id": "c", "document_id": "d4"}],
        "cited": [[{"document_id": "d5"}]],
    }
    assert chat.referenced_document_ids(payload) == {"d1", "d2", "d3", "d4", "d5"}
    assert chat.referenced_document_ids(None) == set()


def test_scope_is_required_keyword_only():
    """No default: a forgotten scope must fail loudly, not return everything."""
    with pytest.raises(TypeError):
        chat.get_messages("anything")  # type: ignore[call-arg]
