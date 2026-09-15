"""Route-level enforcement. One negative test per route that can reveal a
document exists, plus the concurrency property.

NO LOGIN ROUTE IS EXERCISED HERE and none exists yet. Identity is supplied by
a fixture through `access.set_user_resolver`, deliberately: login is the easy
part, and building it would make this feature feel finished while the
enforcement was the thing still untested.

THE PROPERTY UNDER TEST, on every route: a document the caller may not read is
INDISTINGUISHABLE from one that does not exist. Same status, same body. A 403
where an unknown id gives 404 is an existence oracle - it confirms the document
is real, which is the fact the grant was protecting.
"""

from __future__ import annotations

import concurrent.futures as cf

import fitz
import pytest
from fastapi.testclient import TestClient

from app import access, db, states
from app.config import settings
from app.db import connect
from app.ingest import IngestionWorker
from app.main import app

NOW = "2026-09-05T00:00:00Z"
UNKNOWN = "doc_does_not_exist"


def _shape(response):
    """The parts of an error that must not vary between hidden and unknown."""
    d = response.json().get("detail", {})
    return (response.status_code, d.get("code"), d.get("message"))


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


def _pdf(path, text="Coating system no. 1 shall have a nominal DFT of 280 um. "):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "Section 4.4 Ambient conditions", fontsize=13)
    page.insert_text((72, 130), text * 6, fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


def _upload(client, tmp_path, name, text=None):
    _pdf(tmp_path / name, text) if text else _pdf(tmp_path / name)
    with open(tmp_path / name, "rb") as fh:
        return client.post("/api/documents",
                           files={"file": (name, fh, "application/pdf")}
                           ).json()["document"]["id"]


def _grant(user_id, document_ids):
    """A user, a role, and read grants. The whole authorisation path."""
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
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id,"
                     " granted_at) VALUES (?,?,?)", (user_id, rid, NOW))
        for d in document_ids:
            conn.execute(
                "INSERT OR IGNORE INTO document_role_access (document_id,"
                " role_id, permission, granted_at) VALUES (?,?,'read',?)",
                (d, rid, NOW))


@pytest.fixture
def two_documents(tmp_path, monkeypatch):
    """`visible` is granted to u1; `hidden` is granted to nobody."""
    client = TestClient(app)
    visible = _upload(client, tmp_path, "visible.pdf")
    hidden = _upload(client, tmp_path, "hidden.pdf",
                     text="Stripe coating shall be applied to every weld seam. ")
    assert visible != hidden, (
        "the two uploads deduplicated to ONE document - identical bytes have "
        "the same sha256, so every test using this fixture would be asserting "
        "against a single document and passing vacuously")
    for d in (visible, hidden):
        IngestionWorker().process(d)
    _grant("u1", [visible])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: "u1")
    return client, visible, hidden


# ------------------------------- a hidden document looks like a missing one

DOCUMENT_ROUTES = [
    "/api/documents/{id}",
    "/api/documents/{id}/pages",
    "/api/documents/{id}/pages/1/image",
    "/api/documents/{id}/chunks",
    "/api/documents/{id}/excluded",
]


@pytest.mark.parametrize("template", DOCUMENT_ROUTES)
def test_a_hidden_document_is_indistinguishable_from_a_missing_one(
        two_documents, template):
    client, visible, hidden = two_documents
    allowed = client.get(template.format(id=visible))
    forbidden = client.get(template.format(id=hidden))
    unknown = client.get(template.format(id=UNKNOWN))

    assert allowed.status_code == 200, f"{template} denied an authorised read"
    assert forbidden.status_code == unknown.status_code == 404, (
        f"{template} answered {forbidden.status_code} for a hidden document "
        f"and {unknown.status_code} for an unknown one - the difference is an "
        "existence oracle")
    # Compared on CODE AND MESSAGE, not on the whole body: the error echoes
    # the id the caller asked for, and those legitimately differ. Echoing back
    # a caller's own input tells them nothing they did not already know. What
    # would be an oracle is a different code, a different message, or a
    # different status - so those are what this asserts.
    assert _shape(forbidden) == _shape(unknown), (
        f"{template} returns a different error for hidden vs unknown "
        f"({_shape(forbidden)} vs {_shape(unknown)}), which tells the reader "
        "the document is real")


def test_the_document_list_shows_only_what_the_scope_allows(two_documents):
    client, visible, hidden = two_documents
    body = client.get("/api/documents").json()
    ids = {d["id"] for d in body}
    assert ids == {visible}, f"list leaked {ids - {visible}}"


def test_search_cannot_reach_a_hidden_document(two_documents):
    client, visible, hidden = two_documents
    hits = client.get("/api/search", params={"q": "coating dry film thickness",
                                             "limit": 50}).json()["hits"]
    got = {h["document_id"] for h in hits}
    assert hidden not in got, "search leaked a document outside the scope"
    assert got <= {visible}


def test_answer_cannot_quote_a_hidden_document(two_documents):
    client, visible, hidden = two_documents
    body = client.get("/api/answer",
                      params={"q": "coating dry film thickness"}).json()
    passage = body.get("passage")
    if passage:
        assert passage["document_id"] == visible


def test_a_scoped_write_route_hides_the_document_too(two_documents):
    """The stage routes reveal existence just as much as the read routes -
    POSTing to a document you cannot see must not confirm it exists."""
    client, visible, hidden = two_documents
    forbidden = client.post(f"/api/documents/{hidden}/extract")
    unknown = client.post(f"/api/documents/{UNKNOWN}/extract")
    assert forbidden.status_code == unknown.status_code == 404
    assert _shape(forbidden) == _shape(unknown)


def test_a_user_with_no_grants_at_all_sees_an_empty_corpus(
        tmp_path, monkeypatch):
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "a.pdf")
    IngestionWorker().process(doc_id)
    _grant("nobody", [])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: "nobody")

    assert client.get("/api/documents").json() == []
    assert client.get(f"/api/documents/{doc_id}").status_code == 404
    assert client.get("/api/search", params={"q": "coating"}).json()["hits"] == []
    # The line this test stopped one short of for as long as it has existed.
    # /api/documents was scoped and /api/metrics was not, so the Documents
    # screen said "No documents yet" while the Dashboard counted the whole
    # corpus to the same caller in the same session.
    assert client.get("/api/metrics").json()["corpus"]["documents"] == 0


def test_metrics_does_not_name_another_users_unsearchable_document(
        tmp_path, monkeypatch):
    """A filename reaches /api/metrics through `warnings`, not through `corpus`.

    The live probe that found this leak saw only aggregate counts, because
    every document in that corpus was `ready`. That is a property of the data,
    not of the code: `warnings()` interpolates the filename into its message
    for two terminal statuses, and one of them - `no_searchable_content` - is a
    SUCCESSFUL outcome. The document finished, every progress bar reads
    complete, and search can see none of it. It is the likelier of the two to
    occur in normal use, since a scanned PDF whose every chunk is excluded
    lands there with nothing going wrong.

    So the fixture manufactures the state rather than waiting for it.
    """
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "someone-elses.pdf")
    IngestionWorker().process(doc_id)
    with connect() as conn:
        conn.execute("UPDATE documents SET status = ?, error_message = ? WHERE id = ?",
                     (states.NO_SEARCHABLE_CONTENT, "every chunk was excluded", doc_id))

    _grant("nobody", [])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: "nobody")

    body = client.get("/api/metrics").text
    assert "someone-elses.pdf" not in body, (
        "a filename the caller has no grant for reached the metrics response")
    assert doc_id not in body, (
        "a document id the caller has no grant for reached the metrics response")


def test_an_unidentified_caller_sees_nothing_rather_than_everything(
        tmp_path, monkeypatch):
    """The failure this whole design exists to prevent: no identity resolving
    to no filter."""
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "a.pdf")
    IngestionWorker().process(doc_id)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: None)

    assert client.get("/api/documents").json() == []
    assert client.get(f"/api/documents/{doc_id}").status_code == 404


# ----------------------------------------------------------- concurrency

def test_two_concurrent_requests_never_share_scope(tmp_path, monkeypatch):
    """The pass-6 finding, asserted.

    A scope held in module state - a global, a singleton, a mutable default -
    is shared between simultaneous requests, and under two users it hands one
    of them the other's documents. A single-request test cannot see that, so
    these run genuinely in parallel with the resolver reporting a different
    user per thread.
    """
    client = TestClient(app)
    a = _upload(client, tmp_path, "a.pdf")
    b = _upload(client, tmp_path, "b.pdf")
    for d in (a, b):
        IngestionWorker().process(d)
    _grant("ua", [a])
    _grant("ub", [b])
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)

    # Identity per REQUEST, which is the only way two simultaneous requests can
    # carry different users - and it is what a real bearer token does. The
    # scope is still derived server-side from the grant tables; the header only
    # says who is asking, never what they may see.
    access.set_user_resolver(lambda req: req.headers.get("x-test-user"))

    def run(user_id, expected):
        seen = set()
        for _ in range(12):
            body = client.get("/api/documents",
                              headers={"x-test-user": user_id}).json()
            seen |= {d["id"] for d in body}
        return user_id, seen, expected

    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, "ua", {a}), pool.submit(run, "ub", {b})]
        results = [f.result() for f in futures]

    for user_id, seen, expected in results:
        assert seen == expected, (
            f"{user_id} saw {seen}, expected {expected} - a scope leaked "
            "across concurrent requests, which means it is being held "
            "somewhere other than the request")


# --------------------------------------------------- the disabled default

def test_auth_disabled_is_the_shipped_default():
    """The DEFAULT, read from a Settings built with no environment at all.

    This assertion used to read `settings.auth_mode == AUTH_DISABLED` against
    the module-level singleton. That was a real check until conftest began
    pinning the mode for the whole session - at which point it was asserting
    the value a fixture had just set, three files away, and could not fail.
    It would have stayed green if the shipped default were flipped to
    `demo_required` tomorrow.

    A fresh `Settings()` is what the claim was always about: what a deployment
    gets when it sets nothing. `_env_file=None` is the important half - without
    it pydantic-settings reads `backend/.env`, and on a developer machine that
    file says `demo_required`, so the test would assert the developer's local
    configuration rather than the shipped default.
    """
    from app.config import Settings

    assert Settings(_env_file=None).auth_mode == access.AUTH_DISABLED, (
        "the shipped default is no longer 'disabled' - every pre-existing test "
        "runs under that default, and changing it silently changes what they "
        "prove")


def test_auth_disabled_changes_nothing(tmp_path):
    """Every pre-existing test runs under this. It is what proves the
    enforcement is additive, and what makes the rollback a config change."""
    assert settings.auth_mode == access.AUTH_DISABLED
    client = TestClient(app)
    doc_id = _upload(client, tmp_path, "a.pdf")
    IngestionWorker().process(doc_id)
    assert {d["id"] for d in client.get("/api/documents").json()} == {doc_id}
    assert client.get(f"/api/documents/{doc_id}").status_code == 200
    # The scope object still exists and still filters - it just contains
    # everything. The enforcement path is identical in both modes, which is
    # what makes the 518 pre-existing tests a real exercise of it rather than
    # a run around it.
    scope = access.unrestricted_scope()
    assert scope.unrestricted is True
    assert doc_id in scope.allowed_document_ids
