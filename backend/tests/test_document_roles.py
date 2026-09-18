"""Where a document's ROLE comes from: a subfolder, or an administrator.

TWO WRITERS, ONE COLUMN. The watched folder assigns a role from the subfolder
a file was dropped in, and the bulk endpoint assigns one to a selection an
administrator made. Both go through `classification.set_role` and this file is
the proof that neither of them acquired a shortcut.

THE PROPERTY THIS FILE EXISTS FOR, above all the others:

    THE FOLDER DECIDES. THE FILENAME NEVER DOES.

A corpus of 272 files named `SAES-*` makes a filename rule look about 97%
right, and the other 3% is a contractor's reply named after the standard it
answers being adopted AS that standard - after which the submittal is reviewed
against itself, found compliant, and cited with real page numbers. So the
regression guard here drops a file named exactly like a standard into the
folder ROOT and asserts it comes out with NO role. That test is written to
fail the day somebody adds "and if the name starts with SAES-, assume it is a
standard", which is the cheapest-looking improvement anyone could make to this
feature.

Every watcher test drives `watcher.scan_once()` - the real pipeline, the same
callable the background thread runs - rather than calling the role helper
directly. A test that called `role_for()` and asserted it returns
COMPANY_STANDARD would pass with the watcher never wired to it at all, which
is species one of this project's vacuous-test defect: standing somewhere the
feature cannot fail you.
"""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from app import access, auth, classification, db
from app import watcher as watcher_mod
from app.config import settings
from app.db import connect
from app.main import app

NOW = "2026-09-19T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """A private database, a private store, a fresh watcher, a real signing key.

    `reset_watcher` is not optional: the two-scan stability rule lives in the
    watcher's in-memory dictionaries, and one inherited from another test would
    already believe it has seen this test's files.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "watch_folder", "")
    monkeypatch.setattr(settings, "watch_owner_email", "")
    # Generated per test. There is no demo credential in this repository.
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    db.reset_connection()
    db.init_db()
    watcher_mod.reset_watcher()
    yield
    watcher_mod.reset_watcher()
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


@pytest.fixture
def drop_folder(tmp_path, monkeypatch):
    folder = tmp_path / "dropbox"
    folder.mkdir(parents=True)
    monkeypatch.setattr(settings, "watch_folder", str(folder))
    return folder


def pdf_bytes(body: bytes = b"x" * 5000) -> bytes:
    """A real PDF as far as `upload.ingest`'s magic-byte check is concerned."""
    return b"%PDF-1.4\n" + body + b"\n%%EOF\n"


def drop(folder, relative: str, body: bytes) -> None:
    path = folder / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def ingest(folder, relative: str, body: bytes) -> dict:
    """Put a file in the folder and run the watcher until it settles.

    TWO SCANS, because that is the feature: a file is eligible only once it has
    been seen unchanged twice. Going through this rather than reaching for the
    helper is what makes these tests statements about the watcher.
    """
    drop(folder, relative, body)
    watcher_mod.scan_once()
    return watcher_mod.scan_once()


def role_of(document_id: str) -> str | None:
    row = connect().execute(
        "SELECT document_role FROM document_classification WHERE document_id = ?",
        (document_id,)).fetchone()
    return row["document_role"] if row else None


def only_document() -> str:
    rows = connect().execute("SELECT id FROM documents").fetchall()
    assert len(rows) == 1, f"expected exactly one document, found {len(rows)}"
    return rows[0]["id"]


# ------------------------------------------------------- the subfolder rule

def test_a_pdf_dropped_in_standards_is_ingested_as_a_company_standard(drop_folder):
    """The whole feature, through the real pipeline.

    Asserted on the DATABASE column rather than on the scan's return value: the
    scan dict is this module's own report of itself, and a watcher that said
    "ingested as COMPANY_STANDARD" while writing nothing would pass a test that
    believed it.
    """
    result = ingest(drop_folder, "standards/SAES-A-105.pdf", pdf_bytes(b"a standard"))

    assert result["ingested"] == ["standards/SAES-A-105.pdf"], result
    assert role_of(only_document()) == "COMPANY_STANDARD"


def test_a_pdf_dropped_in_the_root_gets_no_role_even_when_it_looks_like_a_standard(
        drop_folder):
    """THE REGRESSION GUARD. The filename must never decide.

    This file is named exactly like the 272 real standards in the corpus and
    sits in the ROOT, so the only way it can come out untagged is if placement
    is genuinely the only input. An implementation that fell back to "the name
    starts with SAES-" - the obvious, tempting, 97%-correct improvement - fails
    here and nowhere else.

    Untagged is not a failure state. The document is ingested and searchable
    and waits for a human, which is exactly the behaviour that existed before
    subfolders did.
    """
    result = ingest(drop_folder, "SAES-A-105.pdf", pdf_bytes(b"looks official"))

    assert result["ingested"] == ["SAES-A-105.pdf"], result
    document_id = only_document()
    assert role_of(document_id) is None, (
        "a file in the folder root was given a role; the only thing that may "
        "assign one is the subfolder, and this file is not in one")


@pytest.mark.parametrize("subfolder,expected", [
    ("standards", "COMPANY_STANDARD"),
    ("submittals", "CONTRACTOR_SUBMITTAL"),
    ("contracts", "CONTRACT_DOCUMENT"),
    ("supporting", "SUPPORTING_DOCUMENT"),
])
def test_each_subfolder_assigns_its_own_role(drop_folder, subfolder, expected):
    """All four, each carrying different bytes so no two dedup into one."""
    ingest(drop_folder, f"{subfolder}/dropped.pdf", pdf_bytes(subfolder.encode() * 400))

    assert role_of(only_document()) == expected


def test_an_unrecognised_subfolder_is_not_walked_at_all(drop_folder):
    """`archive/` is not in the convention, so it is not scanned.

    The watcher walks the root and the four named folders and NOTHING ELSE,
    which is unchanged from before this feature existed - subfolders were never
    scanned then either, so nothing that used to be ingested stops being.

    The alternative to spell out, since it is the one that looks helpful: walk
    every subfolder and assign a role from any name that matches. Then
    `standards/archive/superseded/` hands COMPANY_STANDARD to documents somebody
    filed precisely because they are NOT current. Two levels of convention is
    one more than anybody will remember.

    `role_for` is asserted directly here as well, because it is the function a
    future walker would ask, and it must answer None for a folder it does not
    know rather than guessing from the name.
    """
    ingest(drop_folder, "archive/old.pdf", pdf_bytes(b"filed away"))

    assert connect().execute(
        "SELECT COUNT(*) AS c FROM documents").fetchone()["c"] == 0, (
        "a file below an unrecognised subfolder was ingested")
    assert watcher_mod.role_for(
        drop_folder / "archive" / "old.pdf", drop_folder) is None


def test_the_subfolders_are_created_by_a_scan(drop_folder):
    """The person has to SEE the folders, or the convention does not exist."""
    assert not (drop_folder / "standards").exists()

    watcher_mod.scan_once()

    for name in ("standards", "submittals", "contracts", "supporting"):
        assert (drop_folder / name).is_dir(), f"{name}/ was not created"


def test_moving_a_file_between_subfolders_uses_where_it_actually_is(drop_folder):
    """The folder it is IN, not the folder it was first seen in.

    Somebody who drops a file in the wrong place and moves it has changed their
    mind, and the second answer is the one that counts. A watcher that
    remembered the first location would silently ignore the correction.
    """
    body = pdf_bytes(b"a vendor datasheet" * 200)
    drop(drop_folder, "submittals/pump.pdf", body)
    watcher_mod.scan_once()             # seen once - not yet eligible

    (drop_folder / "submittals" / "pump.pdf").rename(
        drop_folder / "standards" / "pump.pdf")
    watcher_mod.scan_once()
    result = watcher_mod.scan_once()

    assert result["ingested"] == ["standards/pump.pdf"], result
    assert role_of(only_document()) == "COMPANY_STANDARD", (
        "the role came from where the file was first noticed, not from where "
        "it is")


def test_the_same_filename_in_two_subfolders_is_two_different_files(drop_folder):
    """A standard and a contractor's reply can share a name.

    Before subfolders the watcher keyed everything by bare filename, and
    carrying that forward would make the second file collide with the first:
    seen as already handled and skipped without ever being looked at. Different
    bytes, so this is not the dedup path - these are two genuinely different
    documents.
    """
    drop(drop_folder, "standards/SAES-A-105.pdf", pdf_bytes(b"the standard" * 300))
    drop(drop_folder, "submittals/SAES-A-105.pdf", pdf_bytes(b"the reply" * 300))
    watcher_mod.scan_once()
    result = watcher_mod.scan_once()

    assert sorted(result["ingested"]) == [
        "standards/SAES-A-105.pdf", "submittals/SAES-A-105.pdf"], result
    rows = connect().execute("SELECT id, filename FROM documents").fetchall()
    assert {r["filename"] for r in rows} == {"SAES-A-105.pdf"}, (
        "the two documents were expected to SHARE a filename; that is the point")
    # One filename, two documents, two roles - which is only expressible
    # because the watcher stopped keying by name. Collected as a LIST: keying
    # this by filename collapses the two rows into one and asserts nothing,
    # which is how the first version of this test passed while proving less
    # than it claimed.
    assert sorted(role_of(r["id"]) for r in rows) == [
        "COMPANY_STANDARD", "CONTRACTOR_SUBMITTAL"]


# --------------------------------------------- the already-ingested library

def test_a_duplicate_dropped_into_standards_tags_the_document_it_duplicates(
        drop_folder):
    """THE CASE THAT MAKES THE FEATURE USABLE ON THIS CORPUS.

    All 272 standards here were ingested from the folder root before the
    convention existed. Moving them into `standards/` produces 272 DUPLICATES
    and zero ingests, so a role applied only at ingest time would tag exactly
    none of them - silently, while reporting a clean scan. The documented way
    to tag the library would do nothing at all.

    The first half of this test asserts the document really is untagged first,
    so the second half is standing somewhere it can fail.
    """
    body = pdf_bytes(b"a standard already in the corpus" * 100)
    ingest(drop_folder, "SAES-A-105.pdf", body)
    document_id = only_document()
    assert role_of(document_id) is None, "the setup did not produce an untagged document"

    result = ingest(drop_folder, "standards/SAES-A-105.pdf", body)

    assert result["duplicate"] == ["standards/SAES-A-105.pdf"], result
    assert only_document() == document_id, "the duplicate was copied in again"
    assert role_of(document_id) == "COMPANY_STANDARD"


def test_a_duplicate_never_overwrites_a_role_a_person_already_set(drop_folder):
    """The folder is a convenience. It is not an authority.

    A correction made in the UI that a file sitting in a folder undoes on the
    next scan is a correction that does not survive, and the person has no way
    to see it happen - the scan reports a duplicate either way.
    """
    body = pdf_bytes(b"filed in the wrong folder" * 100)
    ingest(drop_folder, "standards/thing.pdf", body)
    document_id = only_document()
    classification.set_role(document_id, "CONTRACTOR_SUBMITTAL")

    # Re-drop the same bytes into standards/ under another name: a duplicate,
    # in a role folder, against a document somebody has since re-tagged.
    ingest(drop_folder, "standards/thing-copy.pdf", body)

    assert role_of(document_id) == "CONTRACTOR_SUBMITTAL", (
        "the watcher overwrote a role that a person set")


def test_set_role_reports_whether_it_changed_anything():
    """`only_if_unset` is the rule above, in the one function that holds it."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at) VALUES ('d1','a.pdf','sha',1,'/tmp/a','ready',?)",
            (NOW,))

    assert classification.set_role("d1", "COMPANY_STANDARD") is True
    assert classification.set_role("d1", "COMPANY_STANDARD") is False, (
        "re-applying the same role reported a change")
    assert classification.set_role(
        "d1", "CONTRACTOR_SUBMITTAL", only_if_unset=True) is False
    assert role_of("d1") == "COMPANY_STANDARD"
    assert classification.set_role("d1", "CONTRACTOR_SUBMITTAL") is True
    assert role_of("d1") == "CONTRACTOR_SUBMITTAL"


def test_set_role_refuses_a_role_outside_the_vocabulary():
    """The column is plain TEXT. This is the only thing standing in the way.

    It matters here more than at the route, because the WATCHER calls this
    function directly from a background thread with nobody reading the output.
    """
    with pytest.raises(classification.UnknownRole):
        classification.set_role("d1", "STANDARD")       # nearly right, and wrong


# -------------------------------------------------------- the bulk endpoint

def _admin_and_documents(monkeypatch, count: int = 3) -> list[str]:
    """An admin who may read `count` documents, and one they may not.

    Modelled on test_classification_api.py's fixture, including the detail that
    cost that file a debugging session: EVERY document is granted to the admin
    capability, because `admin.grant_on_upload` does that in production so a
    document no administrator can see cannot exist. The route asks two
    questions - do you hold the capability, and may you read this document -
    and an admin with no grant correctly fails the second.
    """
    with connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('boss','boss@example.test','boss','h',?)", (NOW,))
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('clerk','clerk@example.test','clerk','h',?)", (NOW,))
        conn.execute(
            "INSERT INTO roles (id,name,description,kind,created_at)"
            " VALUES ('role_admin','admin','admin','capability',?)", (NOW,))
        conn.execute(
            "INSERT INTO roles (id,name,description,kind,created_at)"
            " VALUES ('role_proc','Process','Process','discipline',?)", (NOW,))
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at)"
            " VALUES ('boss','role_admin',?)", (NOW,))
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at)"
            " VALUES ('clerk','role_proc',?)", (NOW,))

    ids = [f"doc{n}" for n in range(count)]
    for doc_id in ids:
        with connect() as conn:
            conn.execute(
                "INSERT INTO documents (id,filename,sha256,size_bytes,"
                "stored_path,status,uploaded_at)"
                " VALUES (?,?,?,1,?,'ready',?)",
                (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"/tmp/{doc_id}", NOW))
            for role_id in ("role_admin", "role_proc"):
                conn.execute(
                    "INSERT OR IGNORE INTO document_role_access (document_id,"
                    "role_id,permission,granted_at,granted_by)"
                    " VALUES (?,?,'read',?,NULL)", (doc_id, role_id, NOW))

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda r: r.headers.get("x-test-user") or None)
    return ids


def as_admin(user: str = "boss") -> dict:
    """Both headers, because the route asks both questions.

    `admin.current_admin` resolves identity through `auth.resolve_user_id` and
    nothing else, so the scope resolver a test installs cannot satisfy it - the
    admin gate is deliberately not reachable by a header a test sets.
    """
    return {"x-test-user": user,
            "Authorization": f"Bearer {auth.issue_token(user)}"}


def test_bulk_sets_the_role_on_every_document_named(monkeypatch):
    ids = _admin_and_documents(monkeypatch)

    response = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": ids, "document_role": "COMPANY_STANDARD"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["updated"] == ids
    assert body["failed"] == []
    assert body["requested"] == 3
    assert all(role_of(i) == "COMPANY_STANDARD" for i in ids)


def test_a_non_admin_cannot_bulk_set_roles(monkeypatch):
    """THE SAME GATE AS THE SINGLE-DOCUMENT ROUTE, NOT A LOOSER ONE.

    A bulk endpoint is the classic place for an authorisation check to become a
    formality. `clerk` may READ all three documents - the scope check passes -
    so the only thing that can refuse them is the admin capability, which is
    what makes this test about the gate rather than about grants.

    And the column is checked afterwards. A 404 with the write already done is
    a test that passes while the feature leaks, and the status code alone
    cannot tell those apart.
    """
    ids = _admin_and_documents(monkeypatch)

    response = TestClient(app).post(
        "/api/documents/bulk/role",
        headers={"x-test-user": "clerk",
                 "Authorization": f"Bearer {auth.issue_token('clerk')}"},
        json={"document_ids": ids, "document_role": "COMPANY_STANDARD"})

    assert response.status_code == 404, response.text
    assert all(role_of(i) is None for i in ids), (
        "the request was refused and the roles were written anyway")


def test_an_unauthenticated_caller_cannot_bulk_set_roles(monkeypatch):
    """No token at all. The same refusal, and the same check on the column."""
    ids = _admin_and_documents(monkeypatch)

    response = TestClient(app).post(
        "/api/documents/bulk/role",
        json={"document_ids": ids, "document_role": "COMPANY_STANDARD"})

    assert response.status_code in (401, 404), response.text
    assert all(role_of(i) is None for i in ids)


def test_a_document_outside_the_callers_scope_is_not_written(monkeypatch):
    """Scope is asked PER DOCUMENT, not once for the request.

    `doc_secret` is granted to nobody, so even an administrator fails the
    second question the route asks. The other two are written, and this one is
    named in `failed` as `not_found` - the same answer an id that does not
    exist gets, because a distinct 'forbidden' would confirm it is real.
    """
    ids = _admin_and_documents(monkeypatch)
    with connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
            "status,uploaded_at)"
            " VALUES ('doc_secret','secret.pdf','sha-s',1,'/tmp/s','ready',?)",
            (NOW,))

    response = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": [*ids, "doc_secret"],
              "document_role": "COMPANY_STANDARD"})

    assert response.status_code == 207, response.text
    body = response.json()
    assert body["failed"] == [{"document_id": "doc_secret", "reason": "not_found"}]
    assert role_of("doc_secret") is None
    assert all(role_of(i) == "COMPANY_STANDARD" for i in ids)


def test_a_mix_of_real_and_unknown_ids_names_every_one_that_failed(monkeypatch):
    """A partial write must be impossible to mistake for a complete one.

    Two signals, deliberately: `failed` names the ids, and the status is 207.
    A client that reads only the body and a client that reads only the status
    code both learn that something did not happen - and 'updated 3 of 5' with
    no names is exactly the response that tells somebody there is a problem
    while making it impossible to find.
    """
    ids = _admin_and_documents(monkeypatch)

    response = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": [ids[0], "ghost-1", ids[1], "ghost-2"],
              "document_role": "CONTRACTOR_SUBMITTAL"})

    assert response.status_code == 207, response.text
    body = response.json()
    assert [f["document_id"] for f in body["failed"]] == ["ghost-1", "ghost-2"]
    assert body["updated"] == [ids[0], ids[1]]
    assert body["requested"] == 4
    # The real ones were still written. Refusing all four because two were
    # stale would make the person redo a selection to get this same result.
    assert role_of(ids[0]) == "CONTRACTOR_SUBMITTAL"
    assert role_of(ids[2]) is None, "a document not named in the request was written"


def test_bulk_separates_documents_it_changed_from_ones_that_already_matched(
        monkeypatch):
    """`unchanged` is not `updated`, and counting it as one inflates every
    confirmation the UI shows."""
    ids = _admin_and_documents(monkeypatch)
    classification.set_role(ids[0], "COMPANY_STANDARD")

    body = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": ids, "document_role": "COMPANY_STANDARD"}).json()

    assert body["unchanged"] == [ids[0]]
    assert body["updated"] == [ids[1], ids[2]]


def test_bulk_sets_the_role_without_erasing_any_other_metadata(monkeypatch):
    """IT IS NOT THE PUT. The PUT replaces the whole classification record.

    Reusing it for bulk would wipe the title, revision, project and subjects on
    every document in the selection - metadata a person typed, destroyed by an
    action that said it was setting a role. Nothing in the response would say
    so.
    """
    ids = _admin_and_documents(monkeypatch)
    classification.confirm(
        ids[0], doc_type="Document", discipline="Process", doc_class="Datasheet",
        subject_ids=[], confirmed_by="boss",
        metadata={"title": "Centrifugal Pump Datasheet", "revision": "B",
                  "project": "Train 2"})

    TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": [ids[0]], "document_role": "COMPANY_STANDARD"})

    row = classification.of_document(ids[0])
    assert row["document_role"] == "COMPANY_STANDARD"
    assert row["title"] == "Centrifugal Pump Datasheet", "the bulk write erased the title"
    assert row["revision"] == "B"
    assert row["project"] == "Train 2"
    assert row["doc_type"] == "Document", "the bulk write erased the type axis"
    assert row["discipline"] == "Process"


def test_an_empty_selection_is_refused_rather_than_answered_with_a_cheerful_zero(
        monkeypatch):
    """"0 documents updated" with a 200 is what a lost selection looks like."""
    _admin_and_documents(monkeypatch)

    response = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": [], "document_role": "COMPANY_STANDARD"})

    assert response.status_code == 422, response.text


def test_a_role_outside_the_vocabulary_is_refused_before_it_reaches_the_column(
        monkeypatch):
    """The column has no CHECK, so the annotation is the enforcement point.

    A typo stored here is a document that no role filter will ever match -
    invisible in exactly the way a missing document is not.
    """
    ids = _admin_and_documents(monkeypatch)

    response = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": ids, "document_role": "COMPANY_STANDARDS"})

    assert response.status_code == 422, response.text
    assert all(role_of(i) is None for i in ids)


def test_the_same_id_twice_is_counted_and_written_once(monkeypatch):
    """A double-counted selection is a UI bug, not a request to write twice."""
    ids = _admin_and_documents(monkeypatch)

    body = TestClient(app).post(
        "/api/documents/bulk/role", headers=as_admin(),
        json={"document_ids": [ids[0], ids[0]],
              "document_role": "COMPANY_STANDARD"}).json()

    assert body["requested"] == 1
    assert body["updated"] == [ids[0]]
    assert body["unchanged"] == [], (
        "the same id was written twice and reported as both changed and not")
