"""r2 S4: POST /api/reports builds from a message id, and a message belongs to
a conversation that belongs to someone. Another user's message id used to
become a report of their answer (any caller who could read the cited document).
Mutations: scripts/mutations/r2_security.py M1985.
"""

from __future__ import annotations

import json

from app.db import connect

from tests.r2_security_support import h, now, temp_storage, world  # noqa: F401


def _conversation_with_answer(owner: str | None) -> str:
    passage = {"chunk_id": "c1", "document_id": "doc_sub", "page_start": 1, "page_end": 1,
               "text": "Invented passage text.", "score": 1.0, "section": "1.1",
               "filename": "SUBMITTAL-A-001.pdf"}
    with connect() as conn:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at,"
                     " owner_user_id) VALUES ('conv1', 't', ?, ?, ?)", (now(), now(), owner))
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " created_at) VALUES ('m_q', 'conv1', 1, 'user', 'a question', ?)",
                     (now(),))
        conn.execute("INSERT INTO messages (id, conversation_id, ordinal, role, text,"
                     " answer_type, payload, created_at)"
                     " VALUES ('m_a', 'conv1', 2, 'assistant', 'an answer', 'extract', ?, ?)",
                     (json.dumps({"passage": passage}), now()))
    return "m_a"


def _reports() -> int:
    try:
        return connect().execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    except Exception:  # noqa: BLE001 - no table means no report was made
        return 0


def test_another_users_message_cannot_become_a_report(world):
    message = _conversation_with_answer(owner="u_sub")
    # u_full can read the cited document, but the conversation is not theirs.
    r = world.post("/api/reports", json={"message_id": message}, headers=h("u_full"))
    assert r.status_code == 404, r.text
    assert r.json()["detail"]["code"] == "not_found"
    assert _reports() == 0, "a report was written from a conversation the caller does not own"


def test_an_unowned_conversation_is_for_the_admin_only(world):
    message = _conversation_with_answer(owner=None)
    assert world.post("/api/reports", json={"message_id": message},
                      headers=h("u_full")).status_code == 404


def test_the_owner_is_not_stopped_by_the_ownership_check(world):
    message = _conversation_with_answer(owner="u_sub")
    r = world.post("/api/reports", json={"message_id": message}, headers=h("u_sub"))
    assert r.status_code == 200, \
        "the ownership check refused the conversation's own owner: " + r.text
