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


# --- s2's review of #1076: the review SAYS it left held standards out, and an
# --- administrator can release one (owner's option a, 19 Oct 2026).


def _run(run_id: str, outcome: dict | None = None) -> None:
    import json

    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES ('sub','s.pdf','sha-sub',1,'s.pdf','ready',1,?)",
            (AFTER,),
        )
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, created_at, updated_at, outcome_json)"
            " VALUES (?, 'sub', 'completed', ?, ?, ?)",
            (
                run_id,
                AFTER,
                AFTER,
                json.dumps(outcome) if outcome is not None else None,
            ),
        )


def test_held_readable_is_exactly_what_selection_leaves_out():
    held = _standard("std-eng", uploader="u-eng")
    admin = _standard("std-adm", uploader="u-admin")
    old = _standard("std-old", uploader="u-eng", at=BEFORE)
    scope = frozenset({held, admin, old})
    assert csc.held_readable(scope) == [held]
    assert csc.held_readable(frozenset({admin, old})) == []  # not readable -> not named
    assert csc.held_readable(frozenset()) == []
    assert held not in standards.selectable_standard_ids(allowed_document_ids=scope)


def test_the_run_note_states_the_count_and_the_option_a_boundary():
    assert csc.run_note([]) is None
    note = csc.run_note(["std-eng"])
    assert note["count"] == 1 and note["standard_document_ids"] == ["std-eng"]
    assert note["confirm_from"] == "2026-10-18T00:00:00"
    assert note["sentence"] == (
        "1 Company standard was not used in this review: uploaded by a non-administrator, "
        "waiting for an administrator's confirmation. "
        "Company standards uploaded before 2026-10-18 count as confirmed."
    )
    assert csc.run_note(["a", "b"])["sentence"].startswith(
        "2 Company standards were not used"
    )


def test_record_on_run_adds_the_note_and_keeps_the_stored_outcome():
    import json

    _run("run-1", {"code": "Approved with Comments", "missing_references": []})
    csc.record_on_run("run-1", ["std-eng"])
    with db.connect() as conn:
        stored = json.loads(
            conn.execute(
                "SELECT outcome_json FROM review_runs WHERE id = 'run-1'"
            ).fetchone()[0]
        )
    assert stored["code"] == "Approved with Comments"  # nothing else is lost
    assert stored[csc.RUN_NOTE_KEY]["count"] == 1
    _run("run-2", {"code": "Approved"})
    csc.record_on_run("run-2", [])  # nothing held: nothing written
    with db.connect() as conn:
        assert (
            csc.RUN_NOTE_KEY
            not in conn.execute(
                "SELECT outcome_json FROM review_runs WHERE id = 'run-2'"
            ).fetchone()[0]
        )


def test_the_standards_route_names_only_held_standards_this_reader_may_read():
    from app import access
    from app.api import run_standards

    note = csc.run_note(["std-a", "std-b"])
    reader = access.AccessScope(
        user_id="u-x", allowed_document_ids=frozenset({"std-a"})
    )
    shown = run_standards._held_note({csc.RUN_NOTE_KEY: note}, reader)
    assert shown["standard_document_ids"] == ["std-a"]  # rule 5: ids narrowed
    assert (
        shown["count"] == 2 and shown["sentence"] == note["sentence"]
    )  # the run's own words
    assert run_standards._held_note({}, reader) is None


def test_the_admin_list_and_confirm_release_a_held_standard():
    from fastapi import HTTPException

    from app.api import admin as admin_api

    held = _standard("std-eng", uploader="u-eng")
    _standard("std-old", uploader="u-eng", at=BEFORE)
    listed = csc.list_held()
    assert [r["id"] for r in listed] == [held]  # before the cut-off: not listed
    assert listed[0]["filename"] == "std-eng.pdf" and listed[0]["uploaded_at"] == AFTER

    actor = {"id": "u-admin", "email": "u-admin@example.invalid"}
    assert admin_api.admin_confirm_company_standard(held, actor=actor) == {
        "document_id": held,
        "confirmed": True,
    }
    assert (
        admin_api.admin_confirm_company_standard(held, actor=actor)["confirmed"]
        is False
    )
    assert held in standards.selectable_standard_ids(
        allowed_document_ids=frozenset({held})
    )
    assert csc.list_held() == []

    for doc, who in (("no-such-doc", actor), (held, None)):  # unknown id; no identity
        with pytest.raises(HTTPException) as err:
            admin_api.admin_confirm_company_standard(doc, actor=who)
        assert err.value.status_code == 404
    _run("run-x")  # creates the submittal 'sub', a document that is no standard
    with pytest.raises(HTTPException) as err:
        admin_api.admin_confirm_company_standard("sub", actor=actor)
    assert err.value.status_code == 422
