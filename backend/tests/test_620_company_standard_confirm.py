"""#620: a Company standard uploaded by a non-admin is held for an
administrator's confirmation before reviews use it. Invented data only.

Who uploaded = the upload route's grant (`document_role_access.granted_by`).
"""

from __future__ import annotations

import pytest

from app import company_standard_confirm as csc
from app import db, standards, submittal_review
from app.config import settings

AFTER, BEFORE = "2026-10-19T09:00:00Z", "2026-09-01T09:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "s620.sqlite")
    monkeypatch.setattr(
        settings, "company_standard_confirm_from", "2026-10-18T00:00:00"
    )
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        for rid, name in (("r-admin", "admin"), ("r-mech", "Mechanical")):
            conn.execute(
                "INSERT OR IGNORE INTO roles (id, name, description, created_at) VALUES (?, ?, 'test', ?)",
                (rid, name, BEFORE),
            )
        ids = {
            name: rid
            for rid, name in conn.execute(
                "SELECT id, name FROM roles WHERE name IN ('admin', 'Mechanical')"
            )
        }
        for uid, role in (("u-admin", ids["admin"]), ("u-eng", ids["Mechanical"])):
            conn.execute(
                "INSERT INTO users (id, email, display_name, password_hash, is_active, created_at)"
                " VALUES (?, ?, ?, 'x', 1, ?)",
                (uid, f"{uid}@example.invalid", uid, BEFORE),
            )
            conn.execute(
                "INSERT INTO user_roles (user_id, role_id, granted_at) VALUES (?, ?, ?)",
                (uid, role, BEFORE),
            )
    yield
    db.reset_connection()


def _role(name: str) -> str:
    with db.connect() as conn:
        return conn.execute("SELECT id FROM roles WHERE name = ?", (name,)).fetchone()[
            "id"
        ]


def _standard(
    doc_id: str, *, uploader: str | None, at: str = AFTER, role: str = "Mechanical"
) -> str:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,?,'ready',3,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", at),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id, suggested_by, document_role)"
            " VALUES (?, 'test', ?)",
            (doc_id, standards.COMPANY_STANDARD),
        )
        if uploader is not None:
            conn.execute(
                "INSERT INTO document_role_access (document_id, role_id, permission, granted_at, granted_by)"
                " VALUES (?, ?, 'read', ?, ?)",
                (doc_id, _role(role), at, uploader),
            )
    return doc_id


def _selectable(*ids: str) -> frozenset[str]:
    return standards.selectable_standard_ids(allowed_document_ids=frozenset(ids))


def test_a_non_admin_upload_is_not_used_by_reviews_until_an_admin_confirms():
    doc = _standard("std-eng", uploader="u-eng")
    assert doc not in _selectable(doc)  # held
    assert csc.held_ids(frozenset({doc})) == {doc}
    assert csc.confirm(doc, actor_user_id="u-admin", actor_username="admin") is True
    assert doc in _selectable(doc)  # confirmed: reviews use it


def test_an_admin_upload_needs_no_confirmation():
    doc = _standard("std-admin", uploader="u-admin", role="admin")
    assert doc in _selectable(doc)


def test_a_standard_granted_before_the_cut_off_is_not_held():
    """Owner option (a) on #620: the 272 standards reviews use today stay in use."""
    doc = _standard("std-old", uploader="u-eng", at=BEFORE)
    assert doc in _selectable(doc)


def test_no_cut_off_holds_every_non_admin_standard(monkeypatch):
    """Owner option (b)/(c): an empty cut-off holds old non-admin standards too."""
    doc = _standard("std-old", uploader="u-eng", at=BEFORE)
    monkeypatch.setattr(settings, "company_standard_confirm_from", "")
    assert doc not in _selectable(doc)


def test_a_standard_with_no_recorded_uploader_is_not_held():
    doc = _standard("std-seeded", uploader=None)
    assert doc in _selectable(doc)


def test_only_an_administrator_may_confirm_and_it_is_audited_once():
    doc = _standard("std-eng", uploader="u-eng")
    with pytest.raises(csc.NotAnAdministrator):
        csc.confirm(doc, actor_user_id="u-eng", actor_username="eng")
    assert doc not in _selectable(doc)
    assert csc.confirm(doc, actor_user_id="u-admin", actor_username="admin") is True
    assert (
        csc.confirm(doc, actor_user_id="u-admin", actor_username="admin") is False
    )  # idempotent
    with db.connect() as conn:
        events = conn.execute(
            "SELECT actor_user_id, resource_id FROM audit_events WHERE action = ?",
            (csc.CONFIRMED_ACTION,),
        ).fetchall()
    assert [tuple(e) for e in events] == [("u-admin", doc)]


def test_a_held_standard_stays_readable_by_its_disciplines():
    """Classification and holding are not access control (CLAUDE.md rule 5):
    the library still lists it for those who may read it."""
    doc = _standard("std-eng", uploader="u-eng")
    listed = {
        r["id"] for r in standards.list_standards(allowed_document_ids=frozenset({doc}))
    }
    assert doc in listed


def test_other_document_roles_are_unaffected():
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('sub','s.pdf','sha-sub',1,'s.pdf','ready',1,?)",
            (AFTER,),
        )
        conn.execute(
            "INSERT INTO document_role_access (document_id, role_id, permission, granted_at, granted_by)"
            " VALUES ('sub', ?, 'read', ?, 'u-eng')",
            (_role("Mechanical"), AFTER),
        )
    assert "sub" not in _selectable("sub")  # never a COMPANY_STANDARD, never selectable
