"""What the system does with authentication ON.

850 tests prove this application works with `AUTH_MODE=disabled`. Almost none
prove it works with `demo_required`, and that asymmetry was invisible until
`backend/.env` started being read: the suite then reported 32 failures from
`backend/` and 0 from the repository root, same commit, same second.

Every one of those 32 was a test that had simply never authenticated. That is
reassuring about the 32 and says nothing about the mode, so `conftest` now pins
`disabled` for the suite and this file exercises the other mode DELIBERATELY,
with a fixture that sets it and grants that actually exist.

The properties here are the ones a client's security reviewer checks first, and
each is written so it fails if enforcement is removed rather than merely
asserting that a request succeeded.
"""

from __future__ import annotations

import fitz
import pytest
from fastapi.testclient import TestClient

from app import access, db
from app.config import settings
from app.db import connect
from app.ingest import IngestionWorker
from app.main import app

NOW = "2026-09-06T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _pdf(path, body):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Section 4.4 Ambient conditions", fontsize=13)
    page.insert_text((72, 130), body * 6, fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


def _upload(client, tmp_path, name, body):
    _pdf(tmp_path / name, body)
    with open(tmp_path / name, "rb") as fh:
        return client.post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]


def _grant(user_id, document_ids):
    conn = connect()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name,"
            " password_hash, created_at) VALUES (?,?,?,?,?)",
            (user_id, f"{user_id}@x", user_id, "hash", NOW))
        rid = f"role_{user_id}"
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, created_at)"
            " VALUES (?,?,?,?)", (rid, rid, rid, NOW))
        # granted_at is NOT NULL with no default - see db.py. A hand-written
        # insert that omits it fails, and nothing else in the suite
        # demonstrates that.
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id,"
                     " granted_at) VALUES (?,?,?)", (user_id, rid, NOW))
        for d in document_ids:
            conn.execute(
                "INSERT OR IGNORE INTO document_role_access (document_id,"
                " role_id, permission, granted_at) VALUES (?,?,'read',?)",
                (d, rid, NOW))


@pytest.fixture
def two_users(tmp_path, monkeypatch):
    """`mine` is granted to u1. `theirs` is granted to u2 and never to u1.

    Two DIFFERENT bodies, because identical bytes share a sha256 and the upload
    path deduplicates them into one document - which would make every assertion
    below a document failing to see itself, and pass.
    """
    client = TestClient(app)
    mine = _upload(client, tmp_path, "mine.pdf",
                   "Coating system no. 1 shall have a nominal DFT of 280 um. ")
    theirs = _upload(client, tmp_path, "theirs.pdf",
                     "Stripe coating shall be applied to every weld seam. ")
    assert mine != theirs, "the two uploads deduplicated into one document"
    for d in (mine, theirs):
        IngestionWorker().process(d)
    _grant("u1", [mine])
    _grant("u2", [theirs])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    return client, mine, theirs


def _as(user_id):
    access.set_user_resolver(lambda req: user_id)


def _as_nobody():
    """No identity at all - the unauthenticated caller under demo_required."""
    access.set_user_resolver(lambda req: None)


# ------------------------------------------------- an unauthenticated caller


def test_an_unauthenticated_caller_is_refused_rather_than_served_everything(
        two_users):
    """The failure the whole design exists to prevent: no identity resolving
    to no filter."""
    client, mine, theirs = two_users
    _as_nobody()

    assert client.get("/api/documents").json() == []
    for doc in (mine, theirs):
        assert client.get(f"/api/documents/{doc}").status_code == 404
    assert client.get("/api/search", params={"q": "coating"}).json()["hits"] == []


# ------------------------------------------------------------- a scoped user


def test_a_scoped_user_sees_only_the_documents_they_were_granted(two_users):
    client, mine, theirs = two_users
    _as("u1")

    listed = {d["id"] for d in client.get("/api/documents").json()}
    assert listed == {mine}, f"leaked {listed - {mine}}"
    assert client.get(f"/api/documents/{mine}").status_code == 200


def test_an_out_of_scope_document_returns_404_and_never_403(two_users):
    """A 403 is an existence oracle: it confirms the document is real, which
    is the fact the grant was protecting. The hidden document and an id that
    was never uploaded must be indistinguishable."""
    client, mine, theirs = two_users
    _as("u1")

    hidden = client.get(f"/api/documents/{theirs}")
    unknown = client.get("/api/documents/doc_never_existed")

    assert hidden.status_code == 404, (
        f"an out-of-scope document answered {hidden.status_code}; a 403 here "
        "would confirm to the caller that the document exists")
    assert unknown.status_code == 404
    assert hidden.json()["detail"]["code"] == unknown.json()["detail"]["code"]
    assert hidden.json()["detail"]["message"] == unknown.json()["detail"]["message"]


# ------------------------------------------------- the Phase S regression


def test_metrics_reports_the_callers_corpus_and_not_the_whole_one(two_users):
    """/api/metrics resolved an access scope and then discarded it, so every
    caller received corpus-wide figures. Measured across three role profiles,
    the corpus block was byte-identical for an admin, a four-document user and
    a user granted nothing, while /api/documents correctly returned 6, 4 and 0.
    """
    client, mine, theirs = two_users
    _as("u1")

    body = client.get("/api/metrics").json()
    assert body["corpus"]["documents"] == 1, (
        f"metrics counted {body['corpus']['documents']} documents for a user "
        "granted exactly one")
    assert body["corpus_wide"] is False, (
        "a non-admin was told these are corpus-wide figures")

    _as_nobody()
    assert client.get("/api/metrics").json()["corpus"]["documents"] == 0


def test_metrics_does_not_name_a_document_the_caller_cannot_read(two_users):
    """`warnings` interpolates a FILENAME into its message, and `jobs.failures`
    returns filename and free-text error_message verbatim. Both are reachable
    only for a document in a terminal failure state, so the fixture
    manufactures one rather than waiting for it - `no_searchable_content` is a
    SUCCESSFUL terminal state and the likelier of the two in normal use.
    """
    client, mine, theirs = two_users
    from app import states
    with connect() as conn:
        conn.execute("UPDATE documents SET status = ?, error_message = ?"
                     " WHERE id = ?",
                     (states.NO_SEARCHABLE_CONTENT, "every chunk excluded",
                      theirs))
    _as("u1")

    body = client.get("/api/metrics").text
    assert "theirs.pdf" not in body, "a filename outside the scope was named"
    assert theirs not in body, "a document id outside the scope was returned"


def test_the_worker_block_hides_the_document_being_processed(two_users):
    """`current_document` is a real document id and `last_error` is free text.

    These are the exact fields moved OFF /api/health so an unauthenticated
    caller could not learn a specific document exists - and the reason recorded
    for moving them was that /api/metrics is scoped. It was not, so they moved
    from one unscoped route to another.
    """
    client, mine, theirs = two_users
    worker = IngestionWorker()
    worker.current_document = theirs
    worker.last_error = {"code": "boom", "message": f"failed on {theirs}"}

    import app.ingest as ingest_mod
    ingest_mod._worker = worker
    try:
        _as("u1")
        body = client.get("/api/metrics").json()
        assert body["worker"]["current_document"] is None, (
            "a caller learned the id of a document they may not read")
        assert body["worker"]["last_error"] is None
        assert theirs not in client.get("/api/metrics").text
    finally:
        ingest_mod._worker = None


def test_the_worker_block_is_shown_when_the_caller_may_read_that_document(
        two_users):
    """The redaction is about SCOPE, not about hiding the field.

    Without this, nulling `current_document` unconditionally would pass the
    test above and quietly break the operator's view - the same shape as a
    fixture that cannot produce the condition it claims to check.
    """
    client, mine, theirs = two_users
    worker = IngestionWorker()
    worker.current_document = mine

    import app.ingest as ingest_mod
    ingest_mod._worker = worker
    try:
        _as("u1")
        body = client.get("/api/metrics").json()
        assert body["worker"]["current_document"] == mine, (
            "a document the caller CAN read was hidden from them")
    finally:
        ingest_mod._worker = None
