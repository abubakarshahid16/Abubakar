"""A conversation belongs to the user who started it - on EVERY route (#81, #80).

Measured live with no token before the fix: GET /api/conversations returned
200 and 80 conversations; GET on one returned 13,491 bytes including a cited
NORSOK M-501 passage verbatim - corpus text reaching a caller for whom
/api/documents returned [] in the same second. POST .../ask wrote a turn into
somebody else's conversation. DELETE removed it and echoed its title.

THE PROPERTY, per route: for a conversation owned by A, a caller who is not A
(no token, or B's token) gets exactly what an unknown id gets - 404, same
code, same message. NEVER 403: a 403 confirms the row exists, which is the
fact ownership protects. The row is unchanged afterwards. And NO field of A's
conversation reaches the response body: not the id, not the title, not a
fragment of any message.

LEGACY ROWS (owner NULL, 81 of 83 on the measured demo database) fail closed
for every identified or unidentified caller while auth is required. Current
main has no administrator-capability schema, so granting those rows implicitly
would introduce a second access model. A later explicit migration may assign
owners without weakening this default.

Identity is supplied exactly the way test_access_routes.py supplies it: a
resolver installed through `access.set_user_resolver`, users and roles written
straight into the grant tables. No login route is exercised.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, db
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-06T00:00:00Z"
UNKNOWN = "conv_never_existed_0"

#: Every field of A's conversation that must never appear in a refusal body.
#: Deliberately distinctive strings, so a substring search cannot match by
#: accident on JSON punctuation or a shared word.
A_TITLE = "minimum radius for rounding sharp edges before blasting ZQX"
A_QUESTION = "what is the minimum radius before blasting ZQX-Q"
A_ANSWER = "Sharp edges shall be rounded minimum radius 2 mm ZQX-A"
LEGACY_TITLE = "legacy question written before there were users ZQX-L"


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


def _user(user_id: str) -> None:
    """Create an identified user holding one ordinary role."""
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name, password_hash,"
            " created_at) VALUES (?,?,?,?,?)",
            (user_id, f"{user_id}@x", user_id, "hash", NOW))
        rid, name = f"role_{user_id}", f"role_{user_id}"
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, created_at)"
            " VALUES (?,?,?,?)", (rid, name, name, NOW))
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at)"
            " VALUES (?,?,?)", (user_id, rid, NOW))


def _as(user_id: str | None) -> None:
    access.set_user_resolver(lambda req: user_id)


def _snapshot(conversation_id: str) -> tuple:
    """Everything about the row and its messages, for an unchanged-afterwards
    check that cannot be satisfied by the row merely still existing."""
    conn = connect()
    conv = conn.execute("SELECT * FROM conversations WHERE id = ?",
                        (conversation_id,)).fetchone()
    msgs = conn.execute(
        "SELECT id, ordinal, role, text FROM messages WHERE conversation_id = ?"
        " ORDER BY ordinal", (conversation_id,)).fetchall()
    return (tuple(conv) if conv else None, tuple(tuple(m) for m in msgs))


def _assert_nothing_of_a_leaked(response, conversation_id: str) -> None:
    body = response.text
    for secret in (conversation_id, A_TITLE, A_QUESTION, A_ANSWER, "ZQX"):
        assert secret not in body, (
            f"a field of another user's conversation reached the body: {secret!r}")


def _assert_same_as_unknown(response, unknown_response) -> None:
    """404 - not 403 - and the same code and message as a missing id."""
    assert response.status_code == 404, (
        f"expected 404; got {response.status_code}. A 403 would confirm the "
        f"conversation exists.")
    assert unknown_response.status_code == 404
    hidden = response.json().get("detail", {})
    unknown = unknown_response.json().get("detail", {})
    assert (hidden.get("code"), hidden.get("message")) == (
        unknown.get("code"), unknown.get("message")), (
        "a hidden conversation is distinguishable from a missing one")


@pytest.fixture
def owned_by_a():
    """A's conversation, with a user turn and an answer turn, so 'no message
    fragment appears' is testing against messages that exist."""
    _user("user_a")
    _user("user_b")
    client = TestClient(app)
    _as("user_a")
    r = client.post("/api/conversations", json={"title": A_TITLE})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    conn = connect()
    with conn:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, ordinal, role, text,"
            " created_at) VALUES (?,?,?,?,?,?)", ("msg_a1", cid, 0, "user", A_QUESTION, NOW))
        conn.execute(
            "INSERT INTO messages (id, conversation_id, ordinal, role, text,"
            " created_at) VALUES (?,?,?,?,?,?)", ("msg_a2", cid, 1, "assistant", A_ANSWER, NOW))
        conn.execute("UPDATE conversations SET message_count = 2 WHERE id = ?",
                     (cid,))
    return client, cid


#: (i) no token at all, (ii) another real user's token.
NOT_A = [pytest.param(None, id="no-token"), pytest.param("user_b", id="user-b")]


# --------------------------------------------------------------------- list


@pytest.mark.parametrize("caller", NOT_A)
def test_list_shows_nothing_of_another_users_conversation(owned_by_a, caller):
    client, cid = owned_by_a
    before = _snapshot(cid)
    _as(caller)
    r = client.get("/api/conversations")
    assert r.status_code == 200
    _assert_nothing_of_a_leaked(r, cid)
    assert r.json()["conversations"] == []
    assert r.json()["total"] == 0, (
        f"total admitted to rows the caller cannot see: {r.json()['total']}")
    assert _snapshot(cid) == before


def test_list_total_is_the_callers_count_not_the_tables(owned_by_a):
    """A correct page with a leaked total is the /api/metrics bug again."""
    client, cid = owned_by_a
    _as("user_b")
    mine = client.post("/api/conversations", json={"title": "b's own"}).json()["id"]
    r = client.get("/api/conversations")
    body = r.json()
    assert [c["id"] for c in body["conversations"]] == [mine]
    assert body["total"] == 1, f"table has 2 rows, caller owns 1, total said {body['total']}"
    _assert_nothing_of_a_leaked(r, cid)


# ---------------------------------------------------------------------- get


@pytest.mark.parametrize("caller", NOT_A)
def test_get_of_another_users_conversation_is_a_missing_one(owned_by_a, caller):
    client, cid = owned_by_a
    before = _snapshot(cid)
    _as(caller)
    hidden = client.get(f"/api/conversations/{cid}")
    unknown = client.get(f"/api/conversations/{UNKNOWN}")
    _assert_same_as_unknown(hidden, unknown)
    _assert_nothing_of_a_leaked(hidden, cid)
    assert _snapshot(cid) == before


# ---------------------------------------------------------------------- ask


@pytest.mark.parametrize("caller", NOT_A)
def test_ask_inside_another_users_conversation_writes_nothing(owned_by_a, caller):
    """An unauthenticated WRITE into someone's conversation - and a model run
    on a machine with 0.3 GB free. Refused before anything is retrieved."""
    client, cid = owned_by_a
    before = _snapshot(cid)
    _as(caller)
    hidden = client.post(f"/api/conversations/{cid}/ask",
                         json={"question": "coating thickness"})
    unknown = client.post(f"/api/conversations/{UNKNOWN}/ask",
                          json={"question": "coating thickness"})
    _assert_same_as_unknown(hidden, unknown)
    _assert_nothing_of_a_leaked(hidden, cid)
    assert _snapshot(cid) == before, "a turn was written into another user's conversation"
    assert connect().execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2


# ------------------------------------------------------------------- rename


def test_there_is_no_rename_route_to_leave_unguarded():
    """The report that prompted #81 named a rename route. None exists. This
    pins that: the day one is added, this fails and ownership coverage for it
    has to be written alongside it."""
    paths = {(m, r.path) for r in app.routes
             for m in getattr(r, "methods", set())
             if r.path.startswith("/api/conversations")}
    assert paths == {
        ("POST", "/api/conversations"),
        ("GET", "/api/conversations"),
        ("GET", "/api/conversations/{conversation_id}"),
        ("DELETE", "/api/conversations/{conversation_id}"),
        ("POST", "/api/conversations/{conversation_id}/ask"),
    }, f"a conversations route appeared without an ownership test: {paths}"


# ------------------------------------------------------------------- delete


@pytest.mark.parametrize("caller", NOT_A)
@pytest.mark.parametrize("confirm", ["", "?confirm=true"], ids=["no-confirm", "confirm"])
def test_delete_of_another_users_conversation_removes_nothing(owned_by_a, caller, confirm):
    """#80: this route had no scope at all; it deleted and echoed the title.
    Checked with and without confirm - a 400 'pass confirm=true' on a hidden
    id would itself confirm the id exists."""
    client, cid = owned_by_a
    before = _snapshot(cid)
    _as(caller)
    hidden = client.delete(f"/api/conversations/{cid}{confirm}")
    unknown = client.delete(f"/api/conversations/{UNKNOWN}{confirm}")
    _assert_same_as_unknown(hidden, unknown)
    _assert_nothing_of_a_leaked(hidden, cid)
    assert _snapshot(cid) == before, "the conversation was deleted by a non-owner"


# ------------------------------------------------------------------- create


def test_a_new_conversation_records_its_creator_as_owner(owned_by_a):
    client, cid = owned_by_a
    row = connect().execute("SELECT owner_user_id FROM conversations WHERE id = ?",
                            (cid,)).fetchone()
    assert row["owner_user_id"] == "user_a"
    _as(None)
    r = client.post("/api/conversations", json={"title": "orphan"})
    assert r.status_code == 401, "a conversation nobody owns was created"


# ------------------------------------------------ legacy rows fail closed


@pytest.fixture
def legacy_row(owned_by_a):
    client, cid = owned_by_a
    with connect() as conn:
        conn.execute(
            "INSERT INTO conversations (id, title, document_id, message_count,"
            " created_at, updated_at, owner_user_id) VALUES (?,?,NULL,0,?,?,NULL)",
            ("conv_legacy000001", LEGACY_TITLE, NOW, NOW))
    return client, cid, "conv_legacy000001"


@pytest.mark.parametrize("caller", NOT_A + [pytest.param("user_a", id="user-a")])
def test_a_legacy_conversation_is_denied_to_ordinary_users(legacy_row, caller):
    client, _, legacy = legacy_row
    _as(caller)
    hidden = client.get(f"/api/conversations/{legacy}")
    _assert_same_as_unknown(hidden, client.get(f"/api/conversations/{UNKNOWN}"))
    assert LEGACY_TITLE not in hidden.text and legacy not in hidden.text
    listing = client.get("/api/conversations")
    assert legacy not in listing.text and LEGACY_TITLE not in listing.text
    assert client.delete(f"/api/conversations/{legacy}?confirm=true").status_code == 404
    assert connect().execute("SELECT COUNT(*) FROM conversations WHERE id = ?",
                             (legacy,)).fetchone()[0] == 1


def test_a_legacy_conversation_fails_closed_until_it_is_assigned(legacy_row):
    """Main has no admin-capability schema yet, so ownerless history is not
    silently granted to any role. A later migration may assign explicit owners."""
    client, _, legacy = legacy_row
    _as("user_a")
    assert client.get(f"/api/conversations/{legacy}").status_code == 404
    assert legacy not in client.get("/api/conversations").text
    assert client.delete(f"/api/conversations/{legacy}?confirm=true").status_code == 404
    assert connect().execute(
        "SELECT COUNT(*) FROM conversations WHERE id = ?", (legacy,)
    ).fetchone()[0] == 1
