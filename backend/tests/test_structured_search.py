from __future__ import annotations

import pytest

from app import db, deliverables, review, risks, structured_search

#: B42: the scope is now REQUIRED, so every call states what it may read.
#: These two pre-existing tests are about matching, not scoping, so they say
#: "everything" explicitly - which is what they always meant and never said.
EVERYTHING = frozenset({"doc_a", "doc_b"})


def test_structured_search_returns_wbs_and_finding_records(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "structured.sqlite")
    db.reset_connection(); db.init_db(); review.ensure_schema(); deliverables.ensure_schema()
    deliverables.create({"wbs_code": "2.1", "title": "Piping review", "deliverable_type": "review"}, created_by=None)
    found = structured_search.search("piping", kind="deliverable",
                                     allowed_document_ids=EVERYTHING,
                                     include_unowned=True)
    assert found and found[0]["wbs_code"] == "2.1"
    db.reset_connection()


def test_structured_search_matches_risk_type_name(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "risk-type.sqlite")
    db.reset_connection(); db.init_db(); risks.ensure_schema()
    risks.create({"risk_type": "schedule", "title": "Late package", "description": "Due date exposure"})
    found = structured_search.search("schedule", kind="risk",
                                     allowed_document_ids=EVERYTHING,
                                     include_unowned=True)
    assert found and found[0]["label"] == "Late package"
    db.reset_connection()


# ==================================================================== B42
#
# The stakeholder branch NEVER consulted the scope mask. The route handed it a
# correct one and the branch discarded it, so a caller holding no grants at all
# received every user's email and display name through
# `deliverable_stakeholders`. The other three kinds guarded and narrowed in SQL
# before a row was read; this one did not, and it is reachable from the UI's own
# `kind` selector.
#
# Two smaller defects in the same module, fixed in the same commit because they
# are the same mistake at different strengths: `allowed_document_ids` defaulted
# to None meaning EVERYTHING, and unowned rows were admitted to every scoped
# result rather than to the admin capability alone (`access.py:105-111`).


def _world(tmp_path, monkeypatch, name):
    """Two documents, one readable and one not, and a stakeholder on each.

    The point of the fixture is that every row exists in two copies - one the
    caller may read, one it may not - so a test cannot pass by returning
    nothing, and cannot pass by returning everything.
    """
    from app.config import settings
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / name)
    db.reset_connection(); db.init_db(); review.ensure_schema()
    deliverables.ensure_schema(); risks.ensure_schema()
    conn = db.connect()
    for doc in ("doc_a", "doc_b"):
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes,"
            " stored_path, uploaded_at) VALUES (?,?,?,?,?,datetime('now'))",
            (doc, f"{doc}.pdf", f"sha-{doc}", 1, f"/tmp/{doc}.pdf"))
    for user, email in (("u_allowed", "allowed@example.test"),
                        ("u_denied", "denied@example.test")):
        conn.execute(
            "INSERT INTO users (id, email, display_name, password_hash,"
            " created_at) VALUES (?,?,?,'x',datetime('now'))",
            (user, email, f"{user} person"))
    # One deliverable per document, plus one belonging to no document at all -
    # the unowned row whose visibility is the admin-only question.
    for did, doc in (("d_a", "doc_a"), ("d_b", "doc_b"), ("d_none", None)):
        conn.execute(
            "INSERT INTO deliverables (id, wbs_code, title, deliverable_type,"
            " document_id, created_at, updated_at)"
            " VALUES (?,?,?,'review',?,datetime('now'),datetime('now'))",
            (did, f"wbs-{did}", f"Piping {did}", doc))
    for did, user in (("d_a", "u_allowed"), ("d_b", "u_denied")):
        conn.execute(
            "INSERT INTO deliverable_stakeholders (deliverable_id, user_id,"
            " role, created_at) VALUES (?,?,'reviewer',datetime('now'))",
            (did, user))
    conn.execute(
        "INSERT INTO risks (id, risk_type, title, description, document_id,"
        " created_at, updated_at)"
        " VALUES ('r_none','schedule','Piping risk','unowned',NULL,"
        "datetime('now'),datetime('now'))")
    conn.commit()
    return conn


def test_a_stakeholder_search_is_scoped_like_every_other_kind(tmp_path, monkeypatch):
    """THE DEFECT. A caller who may read doc_a must not learn that
    denied@example.test exists, because that person is a stakeholder only on a
    deliverable belonging to a document the caller cannot read."""
    _world(tmp_path, monkeypatch, "stakeholder-scope.sqlite")

    found = structured_search.search("person", kind="stakeholder",
                                     allowed_document_ids=frozenset({"doc_a"}),
                                     include_unowned=False)

    emails = {row["email"] for row in found}
    assert emails == {"allowed@example.test"}, \
        f"the stakeholder branch leaked across the scope: {sorted(emails)}"
    db.reset_connection()


def test_an_empty_scope_sees_no_stakeholders(tmp_path, monkeypatch):
    """A caller holding no grants sees nothing - the same answer the other
    three kinds already gave. Empty means NOTHING, never everything."""
    _world(tmp_path, monkeypatch, "stakeholder-empty.sqlite")

    found = structured_search.search("person", kind="stakeholder",
                                     allowed_document_ids=frozenset(),
                                     include_unowned=False)

    assert found == [], f"a caller with no grants received {len(found)} people"
    db.reset_connection()


def test_the_scope_cannot_be_omitted(tmp_path, monkeypatch):
    """There is no unscoped call any more. The permissive default is gone, so
    a caller that forgets the mask fails loudly instead of reading the corpus -
    which is how every sibling module in this codebase already behaves."""
    _world(tmp_path, monkeypatch, "stakeholder-required.sqlite")

    with pytest.raises(TypeError):
        structured_search.search("person", kind="stakeholder")

    db.reset_connection()


def test_an_unowned_row_is_admin_only(tmp_path, monkeypatch):
    """`access.py:105-111` gives rows with no owner to the admin capability and
    to nobody else. This module admitted them to every scoped result, so the
    two rules disagreed; now they agree."""
    _world(tmp_path, monkeypatch, "stakeholder-unowned.sqlite")
    scope = frozenset({"doc_a"})

    ordinary = structured_search.search("Piping", allowed_document_ids=scope,
                                        include_unowned=False)
    admin = structured_search.search("Piping", allowed_document_ids=scope,
                                     include_unowned=True)

    assert {row["id"] for row in ordinary} == {"d_a"}, \
        "an ordinary caller was given a row belonging to no document"
    assert {row["id"] for row in admin} == {"d_a", "d_none", "r_none"}, \
        "the admin capability lost the unowned rows it is entitled to"
    db.reset_connection()


def test_the_route_gives_the_unowned_rows_to_the_admin_capability_alone(
        tmp_path, monkeypatch):
    """The wiring, not just the function. `/api/search/structured` must pass
    the caller's OWN entitlement, so a non-admin identity cannot receive a row
    belonging to no document - and an admin still can. A route that hardcoded
    either answer would pass one half of this and fail the other."""
    from fastapi.testclient import TestClient

    from app import access
    from app.main import app

    _world(tmp_path, monkeypatch, "stakeholder-route.sqlite")
    scope = frozenset({"doc_a"})

    def _as(is_admin: bool) -> list[dict]:
        app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
            user_id="u_allowed", allowed_document_ids=scope,
            capabilities=frozenset({access.ADMIN_CAPABILITY} if is_admin else ()))
        try:
            body = TestClient(app).get("/api/search/structured",
                                       params={"q": "Piping"}).json()
        finally:
            app.dependency_overrides.clear()
        return body["results"]

    assert {row["id"] for row in _as(is_admin=False)} == {"d_a"}, \
        "the route handed an ordinary identity a row belonging to no document"
    assert {row["id"] for row in _as(is_admin=True)} == {"d_a", "d_none", "r_none"}, \
        "the route withheld the unowned rows from the admin capability"
    db.reset_connection()
