"""An upload is a WRITE, and every write needs someone to have made it (#79).

THE DEFECT. `POST /api/documents` took no scope at all. Under
`demo_required` a caller with no identity uploaded a PDF, it was written to
disk, given a document row and an ingestion job - and then `GET
/api/documents` returned `[]` for that same caller. The write succeeded and
the read did not, which is the shape of the whole bug: the document belonged
to no role, so no grant existed for it, so nobody could ever see it. Not the
uploader, not an administrator, not the Documents screen.

Three consequences, and the third is the one that makes this a security issue
rather than a housekeeping one:

  1. An orphan consumes disk and consumes the ingestion worker forever, and
     no screen in the product can show it to anybody.
  2. Ingestion is the most expensive thing this system does - extraction,
     OCR, chunking, embedding, minutes of a 15 W CPU. Anyone who could reach
     the port could queue that without logging in.
  3. A caller who could not read a single document could add one. The
     product's boundary is that access is by grant; this route was outside it.

WHY THE GRANT IS PART OF THE FIX AND NOT A FOLLOW-UP. Refusing the
anonymous upload alone would still leave every authenticated upload an
orphan, because `document_role_access` is written by `admin.grant()` and by
nothing else - no ingestion path assigns a discipline. A route that accepts a
document nobody can then read has not succeeded; it has failed quietly, which
is the failure mode this codebase treats as the serious one.

WHAT IS GRANTED, and why it is two things rather than one. The admin
capability, because an administrator has whole control of the corpus and a
document no administrator can see is unadministrable. AND the uploader's own
discipline roles, because otherwise an engineer's upload vanishes from their
own screen the moment it succeeds - the void in a second costume. An admin
with no discipline gets the first only, which is correct: they can see it.

NOT COVERED HERE. What a duplicate upload should tell a caller who may not
read the document it duplicates. That is a separate decision with real
security consequences either way, and it is not settled by this file.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app import access, admin, db
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-06T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def pdf_bytes(body: bytes = b"x" * 5000) -> bytes:
    return b"%PDF-1.4\n" + body + b"\n%%EOF\n"


def _user(user_id: str, role_name: str, kind: str) -> None:
    """A user holding one role of a stated kind. `kind` is never defaulted:
    'capability' is an administrator and 'discipline' is an engineer, and the
    difference decides what this route grants."""
    role_id = f"role_{role_name}"
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name,"
            " password_hash, created_at) VALUES (?,?,?,?,?)",
            (user_id, f"{user_id}@example.test", user_id, "hash", NOW))
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, kind,"
            " created_at) VALUES (?,?,?,?,?)",
            (role_id, role_name, role_name, kind, NOW))
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at)"
            " VALUES (?,?,?)", (user_id, role_id, NOW))


@pytest.fixture
def identities(monkeypatch):
    """Auth on, identity from a header, one admin and one engineer."""
    _user("admin_user", admin.ADMIN_ROLE, "capability")
    _user("engineer", "Civil-Engineering", "discipline")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: req.headers.get("x-test-user") or None)
    return TestClient(app)


def _upload(client, user: str | None, name: str = "spec.pdf",
            data: bytes | None = None):
    return client.post(
        "/api/documents",
        headers={"x-test-user": user} if user else {},
        files={"file": (name, io.BytesIO(data or pdf_bytes()),
                        "application/pdf")},
    )


def _grants(document_id: str) -> set[str]:
    return {
        r["name"] for r in connect().execute(
            """SELECT r.name FROM document_role_access dra
               JOIN roles r ON r.id = dra.role_id
               WHERE dra.document_id = ? AND dra.permission = 'read'""",
            (document_id,))
    }


# ------------------------------------------------- the anonymous write

def test_an_upload_with_no_identity_is_refused(identities):
    """401, the same answer `/api/auth/me` gives, and the same answer
    `_require_identity_to_write` already gives on conversations. Not 403:
    the caller has not been denied a permission, they have not said who they
    are."""
    response = _upload(identities, None)

    assert response.status_code == 401, (
        f"an unauthenticated caller uploaded a document under "
        f"{settings.auth_mode!r} and got {response.status_code}:\n"
        f"{response.text[:300]}")


def test_a_refused_upload_leaves_nothing_behind(identities):
    """The refusal has to be complete, not cosmetic. A 401 that still wrote
    the row, or still queued the job, would have fixed the status code and
    none of the three consequences - the disk is still consumed and the
    worker still runs."""
    _upload(identities, None)

    with connect() as conn:
        documents = conn.execute("SELECT id, filename FROM documents").fetchall()
        jobs = conn.execute("SELECT id FROM jobs").fetchall()
    assert documents == [], (
        f"a refused upload still created a document row: "
        f"{[tuple(r) for r in documents]}")
    assert jobs == [], (
        f"a refused upload still queued ingestion work: "
        f"{[tuple(r) for r in jobs]} - the expensive half of the defect")

    stored = [p.name for p in settings.upload_dir.glob("*")
              if not p.name.startswith(".incoming-")]
    assert stored == [], f"a refused upload still left a file on disk: {stored}"


def test_the_refusal_says_nothing_about_the_corpus(identities):
    """A 401 body is read by a caller who has proven nothing. It carries the
    same fixed wording as every other unauthenticated refusal and no filename,
    no document id, no path and no count."""
    body = _upload(identities, None, name="intruder.pdf").json()

    text = repr(body)
    for leak in ("intruder", "uploads", str(settings.upload_dir), "doc_"):
        assert leak not in text, (
            f"the 401 body disclosed {leak!r}: {text[:300]}")


# ------------------------------------- the upload that is allowed to happen

def test_an_engineers_upload_is_readable_by_that_engineer(identities):
    """THE VOID, closed. The issue's own reproduction ends `GET
    /api/documents -> []` for the caller who just uploaded. This is that line,
    inverted, and it is the assertion that makes the fix worth having rather
    than merely defensible."""
    response = _upload(identities, "engineer")
    assert response.status_code == 200, response.text
    document_id = response.json()["document"]["id"]

    listed = identities.get(
        "/api/documents", headers={"x-test-user": "engineer"}).json()
    assert [d["id"] for d in listed] == [document_id], (
        "the engineer uploaded a document and their own Documents screen "
        "does not show it - the upload succeeded into a void, which is the "
        "defect rather than a smaller version of it")


def test_an_engineers_upload_is_also_readable_by_an_administrator(identities):
    """Whole control of the corpus means no document is outside it. An
    administrator who cannot see a document cannot grant it, cannot delete it
    and cannot explain it."""
    document_id = _upload(identities, "engineer").json()["document"]["id"]

    listed = identities.get(
        "/api/documents", headers={"x-test-user": "admin_user"}).json()
    assert document_id in [d["id"] for d in listed], (
        "an administrator cannot see a document an engineer uploaded")


def test_the_grant_names_the_admin_capability_and_the_uploaders_discipline(
        identities):
    """Asserted at the grant table rather than only through the screens,
    because "the right rows exist" and "some code path happens to return it"
    are different claims and only the first survives a refactor of the
    read side."""
    document_id = _upload(identities, "engineer").json()["document"]["id"]

    assert _grants(document_id) == {admin.ADMIN_ROLE, "Civil-Engineering"}, (
        f"unexpected grants for an engineer's upload: {_grants(document_id)}")


def test_an_administrator_with_no_discipline_grants_only_the_capability(
        identities):
    """The admin in this fixture holds no discipline, which is the real shape
    of the thing - `access.py` gives an administrator no read bypass. Their
    upload must not invent a discipline row, and must still be readable by
    them through the capability."""
    document_id = _upload(identities, "admin_user").json()["document"]["id"]

    assert _grants(document_id) == {admin.ADMIN_ROLE}, (
        f"an administrator's upload granted more than the capability: "
        f"{_grants(document_id)}")
    listed = identities.get(
        "/api/documents", headers={"x-test-user": "admin_user"}).json()
    assert document_id in [d["id"] for d in listed]


def test_the_engineer_cannot_read_what_another_discipline_uploaded(identities):
    """The grant must not be a wildcard wearing a different hat. A second
    discipline's upload stays outside this engineer's scope."""
    _user("it_person", "IT", "discipline")
    other = _upload(identities, "it_person", name="it.pdf",
                    data=pdf_bytes(b"y" * 5000)).json()["document"]["id"]

    listed = identities.get(
        "/api/documents", headers={"x-test-user": "engineer"}).json()
    assert other not in [d["id"] for d in listed], (
        "an upload granted to IT is visible to Civil-Engineering - the fix "
        "widened access instead of assigning it")


# --------------------------------------------- the mode that is not auth

def test_auth_disabled_still_uploads_without_a_header(monkeypatch):
    """AUTH_MODE=disabled hands every caller every document through
    `unrestricted_scope()`, so an upload route that demanded a header there
    would break the default development mode to protect nothing. This is the
    concession, asserted rather than assumed - and it is the reason the
    existing test_upload.py suite keeps passing unchanged.
    """
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    client = TestClient(app)

    response = client.post(
        "/api/documents",
        files={"file": ("spec.pdf", io.BytesIO(pdf_bytes()),
                        "application/pdf")})

    assert response.status_code == 200, response.text
    assert client.get("/api/documents").json() != [], (
        "under disabled auth the uploader must still be able to read it back")


def test_a_capability_that_is_not_admin_is_never_granted_a_document(
        identities):
    """`kind` decides, and 'capability' is not a synonym for 'admin'.

    Granting every role the uploader happens to hold is the tempting
    one-liner, and it passes every other test in this file because the
    fixture's users hold exactly one role each. A capability is a POWER - it
    says what someone may do - and putting a document row against one makes it
    a discipline by accident: everyone who is ever given that power
    afterwards silently inherits read access to every document uploaded
    before they had it.

    Only the admin capability is granted, and only because whole control of
    the corpus is the point of it.
    """
    _user("auditor", "Reviewer", "capability")
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at)"
            " VALUES (?,?,?)", ("auditor", "role_Civil-Engineering", NOW))

    document_id = _upload(identities, "auditor", name="audited.pdf",
                          data=pdf_bytes(b"z" * 5000)).json()["document"]["id"]

    granted = _grants(document_id)
    assert "Reviewer" not in granted, (
        f"a non-admin capability was granted a document: {granted}. A "
        f"capability is what someone may DO; a grant is what they may READ.")
    assert granted == {admin.ADMIN_ROLE, "Civil-Engineering"}, granted


def test_re_uploading_an_existing_document_does_not_widen_access_to_it(
        identities):
    """THE RE-UPLOAD ATTACK. Granting on every upload rather than only on a
    new one is the other tempting one-liner, and it is worse than the orphan
    it fixes: anyone holding a copy of a file could hand their whole
    discipline read access to the corpus's canonical document by uploading it
    again. `ingest` dedupes by sha256 and returns the EXISTING row, so the
    grant would land on a document that was never theirs.

    An engineer uploads. Somebody in IT uploads the identical bytes. IT must
    not appear in the grants, and the IT caller's own Documents screen must
    not gain the document.
    """
    data = pdf_bytes(b"shared" * 800)
    document_id = _upload(identities, "engineer", name="orig.pdf",
                          data=data).json()["document"]["id"]
    before = _grants(document_id)

    _user("it_person", "IT", "discipline")
    _upload(identities, "it_person", name="same-bytes.pdf", data=data)

    assert _grants(document_id) == before, (
        f"re-uploading an existing document widened its grants from {before} "
        f"to {_grants(document_id)}")
    listed = identities.get(
        "/api/documents", headers={"x-test-user": "it_person"}).json()
    assert document_id not in [d["id"] for d in listed], (
        "a caller gained read access to an existing document by uploading a "
        "copy of it")


# ------------------- a duplicate of something the caller may not read

def test_a_duplicate_the_caller_cannot_read_discloses_nothing(identities):
    """DECIDED: tell them nothing.

    `ingest` dedupes by sha256 and returns the EXISTING row, and the route
    returned that row - filename, status, page count - plus its id in
    `duplicate_of`, to anyone who uploaded matching bytes. Suppressing
    `duplicate_of` alone would have left the filename leaking through
    `document`: the same mistake as gating the host block while the warning
    prose restated the figure.

    So the response says nothing about the document at all. Not its id, not
    its name, not how many pages it has, and not that it exists - which is the
    same answer every read path in this codebase gives for something outside
    the caller's scope, and the reason those return 404 rather than 403.

    `awaiting_grant` is the one thing it does say, and it is about the
    CALLER's request rather than about the corpus: it is true whether or not a
    duplicate was involved, so it is not an existence oracle wearing a
    boolean. Without it the upload would appear to succeed and then never
    appear on any screen, which is the void this whole issue is about.
    """
    # The IT document exists and the engineer holds no grant for it.
    data = pdf_bytes(b"confidential" * 400)
    _user("it_person_setup", "IT", "discipline")
    hidden = _upload(identities, "it_person_setup", name="it-only.pdf",
                     data=data).json()["document"]["id"]

    response = _upload(identities, "engineer", name="my-copy.pdf", data=data)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["duplicate_of"] is None, (
        "the id of a document the caller may not read was disclosed")
    assert body["document"] is None, (
        f"the existing document's record was disclosed: {body['document']}")
    assert body["awaiting_grant"] is True, (
        "the caller was told nothing at all - an upload that appears to "
        "succeed and never appears is the void this issue is about")

    text = repr(body)
    for leak in ("it-only", hidden, "ready", "queued"):
        assert leak not in text, (
            f"the response disclosed {leak!r}: {text[:300]}")


def test_that_duplicate_changes_no_grant_and_no_row(identities):
    """Telling them nothing must also DO nothing. The existing document keeps
    exactly the grants it had, and no second row appears for the same bytes."""
    data = pdf_bytes(b"confidential" * 400)
    _user("it_person_setup", "IT", "discipline")
    hidden = _upload(identities, "it_person_setup", name="it-only.pdf",
                     data=data).json()["document"]["id"]
    before = _grants(hidden)

    _upload(identities, "engineer", name="my-copy.pdf", data=data)

    assert _grants(hidden) == before, (
        f"the duplicate widened grants from {before} to {_grants(hidden)}")
    with connect() as conn:
        rows = conn.execute(
            "SELECT id FROM documents WHERE sha256 = (SELECT sha256 FROM"
            " documents WHERE id = ?)", (hidden,)).fetchall()
    assert len(rows) == 1, f"a second row was created for the same bytes: {rows}"
    listed = identities.get(
        "/api/documents", headers={"x-test-user": "engineer"}).json()
    assert hidden not in [d["id"] for d in listed]


def test_a_duplicate_the_caller_CAN_read_is_still_reported_normally(
        identities):
    """The disclosure rule is about what the caller may not see, not about
    duplicates. Re-uploading your own document still tells you it is already
    there - which is the whole point of the field."""
    data = pdf_bytes(b"mine" * 1200)
    first = _upload(identities, "engineer", name="mine.pdf",
                    data=data).json()["document"]["id"]

    body = _upload(identities, "engineer", name="mine-again.pdf",
                   data=data).json()

    assert body["duplicate_of"] == first
    assert body["document"] is not None
    assert body["job_id"] == ""
    assert body["awaiting_grant"] is False
