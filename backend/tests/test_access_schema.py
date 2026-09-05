"""Access schema: deny-by-default is a property to be proven, not assumed.

NO AUTHENTICATION IS WIRED INTO ANY ROUTE by this schema, and these tests do
not pretend otherwise. They assert the properties the auth layer will stand on,
and they are written first, before anything reads these tables - because a
guard nobody has watched fail is not a guard.

The one thing this schema is for: absence of a grant means no access. There is
no row that means "everyone", no wildcard document id, and no default that
resolves to permitted.
"""

from __future__ import annotations

import sqlite3

import pytest

from app import db
from app.config import settings
from app.db import connect


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


NOW = "2026-09-05T00:00:00Z"


def _user(conn, uid, email="a@b.c"):
    conn.execute(
        "INSERT INTO users (id, email, display_name, password_hash, created_at)"
        " VALUES (?,?,?,?,?)", (uid, email, uid, "argon2:not-a-real-hash", NOW))


def _role(conn, rid, name):
    conn.execute(
        "INSERT INTO roles (id, name, description, created_at) VALUES (?,?,?,?)",
        (rid, name, f"{name} role", NOW))


def _doc(conn, did):
    conn.execute(
        """INSERT INTO documents (id, filename, sha256, size_bytes, stored_path,
                                  status, uploaded_at)
           VALUES (?,?,?,?,?,'ready',?)""",
        (did, f"{did}.pdf", did * 4, 1, f"/{did}", NOW))


def _visible_to(conn, user_id) -> set[str]:
    """The scope resolver, as the auth layer will express it.

    Written as one query on purpose: a user's scope must be derivable from the
    grant tables alone, with no fallback branch in Python that could quietly
    mean "everything" when a join returns nothing.
    """
    return {
        r["document_id"]
        for r in conn.execute(
            """SELECT DISTINCT dra.document_id
               FROM user_roles ur
               JOIN document_role_access dra ON dra.role_id = ur.role_id
               WHERE ur.user_id = ? AND dra.permission = 'read'""",
            (user_id,),
        )
    }


# --------------------------------------------------------- deny by default

def test_a_user_with_no_grant_sees_nothing():
    """THE property. Not 'sees less' - sees nothing."""
    conn = connect()
    with conn:
        _user(conn, "u1")
        _doc(conn, "d1")
        _doc(conn, "d2")
    assert _visible_to(conn, "u1") == set()


def test_a_user_with_a_role_but_no_document_grant_still_sees_nothing():
    """Having a role is not having access. The two tables are separate for
    exactly this reason, and it is worth asserting because 'authenticated'
    reading as 'authorised' is the classic version of this bug."""
    conn = connect()
    with conn:
        _user(conn, "u1")
        _role(conn, "r1", "engineer")
        _doc(conn, "d1")
        conn.execute("INSERT INTO user_roles (user_id, role_id, granted_at)"
                     " VALUES ('u1','r1',?)", (NOW,))
    assert _visible_to(conn, "u1") == set()


def test_a_grant_is_visible_only_to_the_role_that_holds_it():
    conn = connect()
    with conn:
        _user(conn, "u1"); _user(conn, "u2", "b@b.c")
        _role(conn, "r1", "engineer"); _role(conn, "r2", "auditor")
        _doc(conn, "d1"); _doc(conn, "d2")
        conn.execute("INSERT INTO user_roles VALUES ('u1','r1',?,NULL)", (NOW,))
        conn.execute("INSERT INTO user_roles VALUES ('u2','r2',?,NULL)", (NOW,))
        conn.execute("INSERT INTO document_role_access"
                     " VALUES ('d1','r1','read',?,NULL)", (NOW,))
    assert _visible_to(conn, "u1") == {"d1"}
    assert _visible_to(conn, "u2") == set()


def test_two_users_never_share_scope():
    """The plan asks that concurrent requests from different roles never share
    scope. Scope is derived per user from the tables with nothing cached and
    nothing global, so this asserts the derivation, which is where a shared
    mutable would show up."""
    conn = connect()
    with conn:
        _user(conn, "u1"); _user(conn, "u2", "b@b.c")
        _role(conn, "r1", "a"); _role(conn, "r2", "b")
        for d in ("d1", "d2", "d3"):
            _doc(conn, d)
        conn.execute("INSERT INTO user_roles VALUES ('u1','r1',?,NULL)", (NOW,))
        conn.execute("INSERT INTO user_roles VALUES ('u2','r2',?,NULL)", (NOW,))
        conn.execute("INSERT INTO document_role_access"
                     " VALUES ('d1','r1','read',?,NULL)", (NOW,))
        conn.execute("INSERT INTO document_role_access"
                     " VALUES ('d2','r2','read',?,NULL)", (NOW,))
    a, b = _visible_to(conn, "u1"), _visible_to(conn, "u2")
    assert a == {"d1"} and b == {"d2"}
    assert not (a & b)
    assert "d3" not in a | b, "an ungranted document reached somebody"


# ------------------------------------------------- legacy rows are not public

def test_a_legacy_conversation_with_no_owner_is_inaccessible():
    """NULL owner means 'written before there were users'. It must read as
    inaccessible, never as unowned-and-therefore-everyone's. Asserted as a
    query, because that is the form the route will use."""
    conn = connect()
    with conn:
        _user(conn, "u1")
        conn.execute(
            """INSERT INTO conversations (id, title, message_count, created_at,
                                          updated_at, owner_user_id)
               VALUES ('c_legacy','old',0,?,?,NULL)""", (NOW, NOW))
        conn.execute(
            """INSERT INTO conversations (id, title, message_count, created_at,
                                          updated_at, owner_user_id)
               VALUES ('c_mine','mine',0,?,?,'u1')""", (NOW, NOW))
    mine = {r["id"] for r in conn.execute(
        "SELECT id FROM conversations WHERE owner_user_id = ?", ("u1",))}
    assert mine == {"c_mine"}
    assert "c_legacy" not in mine


def test_owner_id_has_no_default_so_a_legacy_row_cannot_look_owned():
    cols = {r["name"]: r for r in connect().execute(
        "PRAGMA table_info(conversations)")}
    assert cols["owner_user_id"]["dflt_value"] is None, (
        "a default owner would attribute every legacy conversation to somebody "
        "who never wrote it")


# ------------------------------------------------------- schema guarantees

def test_there_is_no_row_that_means_everyone():
    """Deny-by-default has to be structural. A wildcard role or a NULL
    document_id in a grant would be a row meaning 'all documents', and the
    NOT NULL constraints are what stop one being written."""
    conn = connect()
    with conn:
        _role(conn, "r1", "engineer")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("INSERT INTO document_role_access"
                         " VALUES (NULL,'r1','read',?,NULL)", (NOW,))


def test_a_grant_cannot_reference_a_document_that_does_not_exist():
    conn = connect()
    with conn:
        _role(conn, "r1", "engineer")
    with pytest.raises(sqlite3.IntegrityError):
        with conn:
            conn.execute("INSERT INTO document_role_access"
                         " VALUES ('ghost','r1','read',?,NULL)", (NOW,))


def test_deleting_a_document_removes_its_grants():
    """A grant outliving its document would be a dangling permission that a
    re-used id could inherit."""
    conn = connect()
    with conn:
        _role(conn, "r1", "engineer")
        _doc(conn, "d1")
        conn.execute("INSERT INTO document_role_access"
                     " VALUES ('d1','r1','read',?,NULL)", (NOW,))
        conn.execute("DELETE FROM documents WHERE id='d1'")
    assert conn.execute(
        "SELECT COUNT(*) FROM document_role_access").fetchone()[0] == 0


def test_deleting_a_user_keeps_the_audit_trail():
    """An audit row that vanishes with its subject is not an audit row."""
    conn = connect()
    with conn:
        _user(conn, "u1")
        conn.execute(
            """INSERT INTO audit_events (at, actor_user_id, action, outcome)
               VALUES (?, 'u1', 'document.read', 'ok')""", (NOW,))
        conn.execute("DELETE FROM users WHERE id='u1'")
    rows = conn.execute("SELECT actor_user_id, action FROM audit_events").fetchall()
    assert len(rows) == 1, "the audit event was deleted with its actor"
    assert rows[0]["actor_user_id"] is None
    assert rows[0]["action"] == "document.read"


def test_the_migration_is_idempotent():
    """Matching the existing style: safe to run on every connection, with no
    version table to consult."""
    conn = connect()
    for _ in range(3):
        db.init_db()
    assert conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()[0] == 1
