"""P5: the progress endpoint answers only the person who asked, and a governed
change cannot stand without its audit row.

Audit failure is simulated with a trigger that aborts every insert into
`audit_events` - the real table, the real transaction. Synthetic data only.
Mutations M890-M896.
"""
from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app import access, admin, auth, db, progress, standards
from app.config import settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "p5.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    db.reset_connection()
    db.init_db()
    access.set_user_resolver(auth.resolve_user_id)
    progress.clear()
    yield
    progress.clear()
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _user(user_id):
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
                     " VALUES (?,?,?,'x',1,?)", (user_id, f"{user_id}@x", user_id, NOW))
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


# --------------------------------------------------------------- progress

def test_progress_is_read_back_only_by_the_one_who_started_it():
    alice, bob = _user("alice"), _user("bob")
    progress.start("p-1", owner="alice")
    client = TestClient(app)
    assert client.get("/api/progress/p-1", headers=alice).status_code == 200
    stranger = client.get("/api/progress/p-1", headers=bob)
    unknown = client.get("/api/progress/p-never", headers=bob)
    assert stranger.status_code == unknown.status_code == 404
    assert stranger.json()["detail"]["message"] == unknown.json()["detail"]["message"]


def test_progress_needs_a_signed_in_caller():
    progress.start("p-1", owner="alice")
    assert TestClient(app).get("/api/progress/p-1").status_code == 401


def test_with_sign_in_disabled_progress_stays_readable(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    progress.start("p-1", owner=None)
    assert TestClient(app).get("/api/progress/p-1").status_code == 200


# --------------------------------------------------------------- audit

def _doc(doc_id):
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
                     " VALUES (?,?,?,1,'/x','ready',?)", (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", NOW))
        conn.execute("INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                     " VALUES ('r-civil','Civil','','discipline',?)", (NOW,))
    return doc_id


def _break_audit():
    with db.connect() as conn:
        conn.execute("CREATE TRIGGER no_audit BEFORE INSERT ON audit_events"
                     " BEGIN SELECT RAISE(ABORT, 'audit table unwritable'); END")


def _grants(doc_id):
    return db.connect().execute("SELECT COUNT(*) FROM document_role_access WHERE document_id = ?",
                                (doc_id,)).fetchone()[0]


def test_a_grant_is_audited_with_its_actor():
    doc = _doc("d1")
    admin.grant(admin.GrantRequest(document_id=doc, discipline="Civil"), {"id": None, "email": "a@x"})
    rows = db.connect().execute("SELECT * FROM audit_events WHERE action = 'admin_grant'").fetchall()
    assert len(rows) == 1 and rows[0]["resource_id"] == doc


def test_a_grant_whose_audit_fails_is_not_granted():
    doc = _doc("d1")
    _break_audit()
    with pytest.raises(Exception, match="audit table unwritable"):
        admin.grant(admin.GrantRequest(document_id=doc, discipline="Civil"), None)
    assert _grants(doc) == 0, "access was granted with no record of who granted it"


def test_a_revoke_whose_audit_fails_is_not_revoked():
    doc = _doc("d1")
    admin.grant(admin.GrantRequest(document_id=doc, discipline="Civil"), None)
    _break_audit()
    with pytest.raises(Exception, match="audit table unwritable"):
        admin.revoke_grant(admin.GrantRequest(document_id=doc, discipline="Civil"), None)
    assert _grants(doc) == 1


def test_a_standards_decision_whose_audit_fails_is_reported_not_swallowed():
    _break_audit()
    with pytest.raises(Exception, match="audit table unwritable"):
        standards._audit("standard.superseded", None, "d1")


def test_login_survives_an_unwritable_audit_but_says_so(monkeypatch):
    from app import errors
    recorded = []
    monkeypatch.setattr(errors, "record_failure", lambda exc, **k: recorded.append(k.get("stage")) or {})
    _break_audit()
    auth._audit("login_failed", "denied", "someone@x")      # does not raise
    assert recorded == ["auth_audit"]


def test_an_admin_change_outside_a_transaction_reports_an_audit_failure():
    """User creation, deactivation and password resets write their audit on
    their own connection - a failure there raises, it is not swallowed."""
    _break_audit()
    with pytest.raises(Exception, match="audit table unwritable"):
        admin._audit("admin_user_created", None, "user", "u1")
