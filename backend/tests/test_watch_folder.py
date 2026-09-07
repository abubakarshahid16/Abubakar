"""The watched drop folder: what it ingests, what it refuses, and what it says.

Every test here calls `watcher.scan_once()` DIRECTLY. That is the same
callable the background thread calls and nothing about the decisions is
duplicated in the loop, so driving it by hand tests the real thing and does
not spend five minutes per interval doing it. A test that started the thread
and slept would prove that `threading` works.

The scans are counted deliberately in each test, because the two-scan
stability rule is the feature: a file must be seen UNCHANGED twice before it
is eligible, so "scan; scan; assert ingested" and "scan; assert nothing" are
both statements about behaviour rather than about timing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import access, db
from app import watcher as watcher_mod
from app.config import settings
from app.db import connect
from app.watch_api import router as watch_router

NOW = "2026-01-01T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    """A private database, a private managed store, and a fresh watcher.

    `reset_watcher` matters as much as `reset_connection`: the stability rule
    lives in the watcher's in-memory dictionaries, so a watcher inherited from
    a previous test would already believe it had seen this test's files.
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "watch_folder", "")
    # Never the developer's configured owner: this file decides ownership per
    # test, and inheriting one from `.env` would make the refusal tests pass
    # or fail depending on whose machine ran them.
    monkeypatch.setattr(settings, "watch_owner_email", "")
    db.reset_connection()
    db.init_db()
    watcher_mod.reset_watcher()
    yield
    watcher_mod.reset_watcher()
    access.set_user_resolver(None)
    db.reset_connection()


#: A directory name that could only reach a response body by being copied out
#: of the configured path. It sits in the folder's PARENT, so every test using
#: this fixture is also a standing check that the parent was there to leak and
#: did not - which is the property the codebase-wide leak sweep asserts.
# A distinctive directory name, so a test asserting the parent path did not
# leak can prove the parent was actually there to leak.
#
# NOT shaped like a credential, deliberately. Named PARENT_DIR_MARKER with an
# uppercase-and-digits value, gitleaks' generic-api-key rule matched it and
# blocked the commit - a fixture marker that trips the secret scanner costs
# every future committer the same investigation, and the tempting way out is
# --no-verify, which skips the scan for everything else in that commit too.
PARENT_DIR_MARKER = "parent-dir-marker-for-the-leak-test"


@pytest.fixture
def drop_folder(tmp_path, monkeypatch):
    folder = tmp_path / PARENT_DIR_MARKER / "dropbox"
    folder.mkdir(parents=True)
    monkeypatch.setattr(settings, "watch_folder", str(folder))
    return folder


def pdf_bytes(body: bytes = b"x" * 5000) -> bytes:
    """The same shape test_upload.py uses - `upload.ingest` validates the
    magic bytes, so this is a real PDF as far as the ingestion path is
    concerned and a fake one as far as a PDF reader would be."""
    return b"%PDF-1.4\n" + body + b"\n%%EOF\n"


def events(outcome: str | None = None) -> list[dict]:
    rows = [dict(r) for r in connect().execute("SELECT * FROM watch_events ORDER BY id")]
    return [r for r in rows if outcome is None or r["outcome"] == outcome]


def document_count() -> int:
    return connect().execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]


# --------------------------------------------------------------- ingestion

def test_a_stable_pdf_is_ingested_exactly_once_across_three_scans(drop_folder):
    """Once, not once per scan.

    The failure this guards is not "nothing happens" - it is a folder that
    re-ingests its own contents every interval, which the sha256 dedup would
    hide as a growing pile of 'duplicate' events while the operator's log
    filled with noise. So the assertion is on the COUNT, over three passes,
    and on the single document row.
    """
    body = pdf_bytes(b"a specification" * 300)
    source = drop_folder / "spec.pdf"
    source.write_bytes(body)

    first = watcher_mod.scan_once()
    assert first["ingested"] == [], "a file seen once has not been seen twice"
    assert first["unstable"] == ["spec.pdf"]
    assert document_count() == 0

    second = watcher_mod.scan_once()
    assert second["ingested"] == ["spec.pdf"]

    third = watcher_mod.scan_once()
    assert third["ingested"] == []
    assert third["already_handled"] == ["spec.pdf"]

    ingested = events("ingested")
    assert len(ingested) == 1, f"expected one ingestion, got {events()}"
    assert ingested[0]["filename"] == "spec.pdf"
    assert ingested[0]["document_id"]
    assert len(ingested[0]["sha256"]) == 64
    assert document_count() == 1

    # The source is the client's. It is copied, never touched.
    assert source.exists(), "the watcher moved or deleted the source file"
    assert source.read_bytes() == body, "the watcher modified the source file"
    # ...and the bytes really did land in managed storage.
    stored = connect().execute("SELECT stored_path FROM documents").fetchone()["stored_path"]
    assert Path(stored).read_bytes() == body


def test_a_file_still_being_written_is_not_ingested_until_it_stops_changing(drop_folder):
    """THE reason this feature polls twice instead of once.

    A large PDF copied onto a share is listed, openable and incomplete for as
    long as the copy takes. Ingesting it there produces a truncated document
    that extracts and answers questions WRONGLY, which is worse than not
    ingesting it at all because it looks like a success. The size changing
    between two passes is what that looks like from here.
    """
    source = drop_folder / "big.pdf"
    source.write_bytes(pdf_bytes(b"first half" * 100))

    watcher_mod.scan_once()                       # seen once, measured
    source.write_bytes(pdf_bytes(b"first half" * 100 + b"second half" * 100))
    growing = watcher_mod.scan_once()             # different size - still copying

    assert growing["ingested"] == []
    assert growing["unstable"] == ["big.pdf"]
    assert document_count() == 0
    assert events() == [], "a partially written file was recorded as a decision"

    settled = watcher_mod.scan_once()             # unchanged since the last pass
    assert settled["ingested"] == ["big.pdf"]
    assert document_count() == 1
    # And the document that landed is the WHOLE file, not the half that was
    # there when the watcher first saw it.
    assert connect().execute(
        "SELECT size_bytes FROM documents").fetchone()["size_bytes"] == source.stat().st_size


# --------------------------------------------------------------- duplicates

def test_a_duplicate_is_announced_once_and_creates_no_second_document(drop_folder):
    """Same bytes under a different name is not a new document.

    Dedup is `upload.find_by_hash`, the same mechanism the upload route uses,
    so a file that arrives in the folder having already been uploaded through
    the app is recognised too. The event is written ONCE: a copy sitting in
    the folder forever must not announce itself every five minutes.
    """
    body = pdf_bytes(b"the same document" * 200)
    (drop_folder / "original.pdf").write_bytes(body)
    watcher_mod.scan_once()
    watcher_mod.scan_once()
    assert document_count() == 1
    original_id = connect().execute("SELECT id FROM documents").fetchone()["id"]

    (drop_folder / "copy.pdf").write_bytes(body)
    watcher_mod.scan_once()
    assert events("duplicate") == [], "a copy was judged before it was stable"
    watcher_mod.scan_once()
    watcher_mod.scan_once()

    duplicates = events("duplicate")
    assert len(duplicates) == 1, f"expected one duplicate event, got {events()}"
    assert duplicates[0]["filename"] == "copy.pdf"
    assert duplicates[0]["document_id"] == original_id
    assert document_count() == 1, "a duplicate created a second document row"
    assert len(events("ingested")) == 1


# ------------------------------------------------------------ one bad file

def test_a_corrupt_pdf_fails_alone_and_the_good_one_beside_it_still_lands(drop_folder):
    """One bad file may not stop the scan.

    The bad file is named so it sorts FIRST: the point is that the failure
    happens before the good file is reached, so a scan that aborted on it
    would leave `good.pdf` un-ingested and this test would fail. Sorting the
    other way would let a broken implementation pass.
    """
    (drop_folder / "corrupt.pdf").write_bytes(b"PK\x03\x04 this is a zip, not a pdf")
    good = pdf_bytes(b"a real one" * 200)
    (drop_folder / "good.pdf").write_bytes(good)

    watcher_mod.scan_once()
    result = watcher_mod.scan_once()

    assert result["failed"] == ["corrupt.pdf"]
    assert result["ingested"] == ["good.pdf"]

    failures = events("failed")
    assert len(failures) == 1
    assert failures[0]["filename"] == "corrupt.pdf"
    # Named as the client's own error - the code the upload route would have
    # answered 400 with - not as an internal failure.
    assert "not_pdf" in (failures[0]["detail"] or "")
    # A failure still records what it was judging, so the event can be matched
    # against the file that is still sitting in the folder.
    assert len(failures[0]["sha256"]) == 64

    assert len(events("ingested")) == 1
    assert document_count() == 1
    assert connect().execute(
        "SELECT filename FROM documents").fetchone()["filename"] == "good.pdf"


def test_the_scan_after_a_failure_still_runs(drop_folder):
    """A failure is recorded once, and does not poison the next scan."""
    (drop_folder / "corrupt.pdf").write_bytes(b"not a pdf")
    watcher_mod.scan_once()
    watcher_mod.scan_once()
    assert len(events("failed")) == 1

    (drop_folder / "later.pdf").write_bytes(pdf_bytes(b"arrived afterwards" * 100))
    watcher_mod.scan_once()
    assert watcher_mod.scan_once()["ingested"] == ["later.pdf"]
    # ...and the corrupt file was not re-reported on either of those passes.
    assert len(events("failed")) == 1


# ---------------------------------------------------------------- ownership

def _grants(document_id: str) -> set[tuple[str, str, str]]:
    """Every grant row on a document as (role_id, permission, granted_by).

    The whole row, not a count and not just the role names: "granted to
    Civil-Engineering" and "granted to Civil-Engineering BY somebody else" are
    different facts, and attribution is what an audit reads.
    """
    return {
        (r["role_id"], r["permission"], r["granted_by"])
        for r in connect().execute(
            "SELECT role_id, permission, granted_by FROM document_role_access"
            " WHERE document_id = ?", (document_id,))
    }


def _owned_folder(drop_folder, monkeypatch, email: str = "owner@example.test"):
    """demo_required, with `email` named as the folder's owner."""
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "watch_owner_email", email)
    return drop_folder


def test_a_named_owner_gets_exactly_the_grants_a_manual_upload_would_give(
        drop_folder, monkeypatch):
    """THE fix, and the anti-escalation assertion in one.

    The administrator names an existing user, and the document ends up with
    precisely the grants `admin.grant_on_upload` gives a manual upload by that
    person: their discipline roles, plus the admin capability. The assertion is
    on the GRANT ROWS and it is an EQUALITY - a subset check would pass a
    watcher that also granted itself Mechanical-Engineering, which is the
    defect worth catching. `Mechanical-Engineering` exists in this database
    precisely so that granting it would be visible.
    """
    _user("owner", "Civil-Engineering", "discipline")
    _user("admin_user", "admin", "capability")
    _user("other", "Mechanical-Engineering", "discipline")
    _owned_folder(drop_folder, monkeypatch)

    (drop_folder / "spec.pdf").write_bytes(pdf_bytes(b"owned" * 400))
    watcher_mod.scan_once()
    result = watcher_mod.scan_once()

    assert result["ingested"] == ["spec.pdf"], f"still refused: {events()}"
    assert document_count() == 1
    doc_id = connect().execute("SELECT id FROM documents").fetchone()["id"]

    assert _grants(doc_id) == {
        ("role_Civil-Engineering", "read", "owner"),
        ("role_admin", "read", "owner"),
    }, "the watcher wrote grants a manual upload by that user would not"

    assert events("ingested")[0]["document_id"] == doc_id


def test_the_auto_ingested_document_reaches_the_owners_discipline_and_no_other(
        drop_folder, monkeypatch):
    """No privilege escalation, asserted through the real authorisation path.

    `access.scope_for_user` is what every route resolves a caller against, so
    asking it is asking the same question the API asks. An engineer in another
    discipline must not gain a document because it arrived through a folder
    rather than through the upload button.
    """
    _user("owner", "Civil-Engineering", "discipline")
    _user("admin_user", "admin", "capability")
    _user("outsider", "Mechanical-Engineering", "discipline")
    _owned_folder(drop_folder, monkeypatch)

    (drop_folder / "spec.pdf").write_bytes(pdf_bytes(b"scoped" * 400))
    watcher_mod.scan_once()
    watcher_mod.scan_once()
    doc_id = connect().execute("SELECT id FROM documents").fetchone()["id"]

    assert access.scope_for_user("owner").may_read(doc_id)
    assert access.scope_for_user("admin_user").may_read(doc_id)
    assert not access.scope_for_user("outsider").may_read(doc_id), (
        "a folder drop widened access beyond what an upload by the owner "
        "would have")


def test_no_configured_owner_is_refused_and_names_the_setting(
        drop_folder, monkeypatch):
    """Refusing is still right when there is nobody to grant to - but the
    refusal has to tell an operator which knob to turn."""
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    (drop_folder / "orphan.pdf").write_bytes(pdf_bytes(b"nobody owns me" * 100))

    watcher_mod.scan_once()
    result = watcher_mod.scan_once()

    assert result["failed"] == ["orphan.pdf"]
    assert document_count() == 0, "an unreadable orphan document was created"
    detail = events("failed")[0]["detail"]
    assert detail == watcher_mod.OWNER_UNSET
    assert "WATCH_OWNER_EMAIL" in detail, "the operator cannot act on this"


def test_an_owner_who_does_not_exist_is_refused_without_echoing_the_address(
        drop_folder, monkeypatch):
    """The refusal reaches the panel every engineer can open.

    `watch_owner_email` is a real person's address that an operator typed into
    a file. Reflecting it back would publish an identity through a status
    screen - the same class of disclosure the `folder` field is withheld for -
    and a typo'd address is still an address. The message says what to fix and
    never what the value is.
    """
    _owned_folder(drop_folder, monkeypatch, "ghost@nowhere.invalid")
    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())

    watcher_mod.scan_once()
    watcher_mod.scan_once()

    assert document_count() == 0
    detail = events("failed")[0]["detail"]
    assert detail == watcher_mod.OWNER_UNKNOWN
    assert "ghost@nowhere.invalid" not in detail, f"the configured email leaked: {detail!r}"
    assert "ghost" not in detail and "nowhere" not in detail
    # And it is a DIFFERENT reason from the unset one - an operator who has
    # set the value needs to know it did not match, not to be told to set it.
    assert detail != watcher_mod.OWNER_UNSET


def test_an_owner_with_no_discipline_is_refused_with_its_own_reason(
        drop_folder, monkeypatch):
    """A user who holds no discipline is the orphan wearing a name.

    `grant_on_upload` would give the document that user's discipline roles -
    of which there are none - plus the admin capability, so it would appear on
    no engineer's screen. Refused, and said so distinctly.
    """
    _user("admin_only", "admin", "capability")
    _owned_folder(drop_folder, monkeypatch, "admin_only@example.test")
    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())

    watcher_mod.scan_once()
    watcher_mod.scan_once()

    assert document_count() == 0
    detail = events("failed")[0]["detail"]
    assert detail == watcher_mod.OWNER_HAS_NO_DISCIPLINE
    assert "discipline" in detail
    assert detail not in (watcher_mod.OWNER_UNSET, watcher_mod.OWNER_UNKNOWN)


def test_a_deactivated_owner_stops_being_an_owner(drop_folder, monkeypatch):
    """Deactivation takes effect on the next scan, not at the next restart.

    `auth.resolve_user_id` re-reads `is_active` on every request for exactly
    this reason; a background thread that cached the answer would keep feeding
    a deactivated person's disciplines.
    """
    _user("owner", "Civil-Engineering", "discipline")
    with connect() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = 'owner'")
    _owned_folder(drop_folder, monkeypatch)
    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())

    watcher_mod.scan_once()
    watcher_mod.scan_once()

    assert document_count() == 0
    assert events("failed")[0]["detail"] == watcher_mod.OWNER_UNKNOWN


def test_with_auth_disabled_nothing_changes_and_no_grant_is_written(
        drop_folder, monkeypatch):
    """The pre-existing mode, untouched.

    `grant_on_upload(id, None)` deliberately writes nothing under `disabled`,
    where `unrestricted_scope()` already gives every caller every document. A
    grant row appearing here would quietly change what disabled mode means.

    THE OWNER IS CONFIGURED AND THE USER REALLY EXISTS, holding both a
    discipline and the admin capability - so `grant_on_upload` would have real
    roles to write if it were ever handed that id. Without those rows present
    this test passed against a watcher that invented an owner under
    `disabled`, because the fabricated id resolved to no roles and therefore
    wrote nothing. The grants have to be REACHABLE for their absence to mean
    anything.
    """
    assert settings.auth_mode == access.AUTH_DISABLED
    _user("owner", "Civil-Engineering", "discipline")
    _user("admin_user", "admin", "capability")
    monkeypatch.setattr(settings, "watch_owner_email", "owner@example.test")
    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())

    watcher_mod.scan_once()
    assert watcher_mod.scan_once()["ingested"] == ["spec.pdf"]

    doc_id = connect().execute("SELECT id FROM documents").fetchone()["id"]
    assert _grants(doc_id) == set(), "disabled mode grew grant rows"
    assert access.unrestricted_scope().may_read(doc_id)


# ------------------------------------------------------------ folder states

def test_a_missing_folder_is_a_reported_state_and_not_a_crash(tmp_path, monkeypatch):
    """A share that is not mounted yet must not end the watcher."""
    monkeypatch.setattr(settings, "watch_folder", str(tmp_path / "not-there"))
    assert watcher_mod.scan_once()["state"] == "missing"
    assert watcher_mod.scan_once()["state"] == "missing"
    assert events() == []
    # The scan still happened, and the status must be able to say when.
    assert watcher_mod.last_scan_at() is not None


def test_an_unset_folder_starts_no_thread_and_says_why():
    assert (settings.watch_folder or "") == ""
    reason = watcher_mod.start_watcher()
    assert isinstance(reason, str) and reason, "start_watcher must state why it did not start"
    assert "watch folder" in reason
    assert watcher_mod.scan_once()["state"] == "disabled"


# --------------------------------------------------------------- the status

def _client() -> TestClient:
    """The router on a bare app. main.py mounts it for real; this file must
    not depend on that wiring existing yet, and mounting it here tests the
    router rather than the application's route table."""
    app = FastAPI()
    app.include_router(watch_router)
    return TestClient(app)


def _user(user_id: str, role_name: str, kind: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name,"
            " password_hash, created_at) VALUES (?,?,?,?,?)",
            (user_id, f"{user_id}@example.test", user_id, "hash", NOW))
        conn.execute(
            "INSERT OR IGNORE INTO roles (id, name, description, kind,"
            " created_at) VALUES (?,?,?,?,?)",
            (f"role_{role_name}", role_name, role_name, kind, NOW))
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at)"
            " VALUES (?,?,?)", (user_id, f"role_{role_name}", NOW))


def test_the_folder_path_is_admin_information_and_an_engineer_never_sees_it(
        drop_folder, monkeypatch):
    """The /api/metrics leak, not recreated.

    The path names the operator's drive layout and the client's share. No
    document grant can entitle anybody to it, so the gate is the capability -
    `scope.is_admin` - and it is the same predicate /api/metrics uses for host
    facts. The engineer still gets a usable answer: enabled, interval, recent
    events. Only the path is withheld.
    """
    _user("admin_user", "admin", "capability")
    _user("engineer", "Civil-Engineering", "discipline")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: req.headers.get("x-test-user") or None)

    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())
    client = _client()

    engineer = client.get("/api/watch/status", headers={"x-test-user": "engineer"})
    assert engineer.status_code == 200, engineer.text
    seen_by_engineer = engineer.json()
    assert seen_by_engineer["enabled"] is True
    assert seen_by_engineer["folder_name"] is None, (
        "the folder reached a non-administrator")
    assert seen_by_engineer["interval_seconds"] == settings.watch_interval_seconds

    admin = client.get("/api/watch/status", headers={"x-test-user": "admin_user"})
    assert admin.status_code == 200, admin.text
    seen_by_admin = admin.json()
    assert seen_by_admin["folder_name"] == "dropbox", (
        "the administrator must see the folder's NAME - a test that only "
        "checked the engineer's None would pass with the field removed "
        "entirely, and one that expected the whole path would enshrine the "
        "leak the sweep found")
    assert str(drop_folder) not in admin.text
    assert PARENT_DIR_MARKER not in admin.text, "the parent directory leaked"

    # An unauthenticated caller is not an administrator either.
    anonymous = client.get("/api/watch/status").json()
    assert anonymous["folder_name"] is None


def test_the_status_reports_the_newest_events_newest_first(drop_folder, monkeypatch):
    """`recent` is the answer to "why has my document not appeared", so it has
    to hold the refusals, in the order they happened."""
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    (drop_folder / "corrupt.pdf").write_bytes(b"not a pdf at all")
    (drop_folder / "good.pdf").write_bytes(pdf_bytes(b"real" * 500))
    watcher_mod.scan_once()
    watcher_mod.scan_once()

    payload = _client().get("/api/watch/status").json()
    assert payload["enabled"] is True
    assert payload["last_scan_at"] == watcher_mod.last_scan_at()
    assert payload["last_scan_at"] is not None
    recent = payload["recent"]
    assert [r["filename"] for r in recent] == ["good.pdf", "corrupt.pdf"], (
        "newest first - `corrupt.pdf` was handled first, so it must be last")
    assert [r["outcome"] for r in recent] == ["ingested", "failed"]
    assert set(recent[0]) == {"filename", "outcome", "at", "detail"}, (
        "the host path must not travel per row either")


def test_the_status_never_caps_the_recent_window_open(drop_folder, monkeypatch):
    """Ten, not everything. A window that grows without bound is a log served
    from an API response."""
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    for n in range(14):
        (drop_folder / f"doc{n:02d}.pdf").write_bytes(pdf_bytes(b"body %d" % n * 100))
    watcher_mod.scan_once()
    watcher_mod.scan_once()
    assert len(events()) == 14

    recent = _client().get("/api/watch/status").json()["recent"]
    assert len(recent) == 10
    assert recent[0]["filename"] == "doc13.pdf"


def test_the_feature_being_off_is_a_200_with_nulls_and_never_an_error():
    """No folder configured is the DEFAULT state of this system. A 404 or a
    503 would send an operator hunting for a fault that does not exist."""
    response = _client().get("/api/watch/status")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "folder_name": None,
        "reachable": None,
        "last_error": None,
        "last_scan_at": None,
        "interval_seconds": None,
        "recent": [],
    }


# ------------------------------------------------- is it actually WORKING?
#
# `enabled` says the folder is CONFIGURED. At the client's site it is a
# network share, and a share can be unmounted, have its permissions revoked,
# or sit behind a VPN that dropped overnight. `reachable` is the difference
# between a panel that is honest about that and one that renders healthy while
# `last_scan_at` quietly ages.

#: A folder name nothing in a safe error message could produce by accident. If
#: this string appears in `last_error`, the path leaked - there is no other way
#: those characters could get there.
SECRET = "RAGINTEL-SECRET-SHARE-42"


def test_reachable_is_null_until_a_scan_has_actually_run(drop_folder):
    """None, not False.

    False is an OBSERVATION - somebody looked and could not read it. Before
    the first scan nobody has looked, and reporting False would claim a
    failure that has not happened, which is the same defect as a measurement
    that has not been taken being reported as 0.
    """
    # THE WATCHER EXISTS AND HAS NOT SCANNED YET. This is the real state
    # after `start_watcher()` and before the first pass completes - the state
    # a status request during startup actually meets - and materialising the
    # singleton is what makes the assertion test the field's INITIAL VALUE
    # rather than the "no watcher at all" shortcut in `last_reachable()`. A
    # version of this test without this line passed against a watcher that
    # initialised `last_reachable = False`.
    watcher_mod.get_watcher()
    assert watcher_mod.last_reachable() is None
    assert watcher_mod.last_error() is None

    configured = _client().get("/api/watch/status").json()
    assert configured["enabled"] is True, "this asserts the NOT-YET state, not the off state"
    assert configured["reachable"] is None
    assert configured["last_error"] is None
    assert configured["last_scan_at"] is None


def test_reachable_is_null_when_the_feature_is_off():
    """Off is not unreachable. Nothing was looked at, so nothing is claimed."""
    watcher_mod.get_watcher()          # started, as it is in production
    off = _client().get("/api/watch/status").json()
    assert off["enabled"] is False
    assert off["reachable"] is None
    assert off["last_error"] is None


def test_a_readable_folder_reports_reachable_and_no_error(drop_folder):
    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())
    watcher_mod.scan_once()

    payload = _client().get("/api/watch/status").json()
    assert payload["reachable"] is True
    assert payload["last_error"] is None
    assert payload["last_scan_at"] is not None


def test_a_missing_folder_reports_unreachable_with_a_reason(tmp_path, monkeypatch):
    """The share that is not mounted. The panel has to SAY so."""
    monkeypatch.setattr(settings, "watch_folder", str(tmp_path / "not-mounted"))
    watcher_mod.scan_once()

    payload = _client().get("/api/watch/status").json()
    assert payload["enabled"] is True, "configured and unreachable is the whole point"
    assert payload["reachable"] is False
    assert payload["last_error"], "unreachable with no reason explains nothing"
    assert "could not be read" in payload["last_error"]


def test_reachability_recovers_when_the_share_comes_back(tmp_path, monkeypatch):
    """A stale error is its own dishonesty: a folder that is fine now must not
    still be reporting last week's outage."""
    folder = tmp_path / "share"
    monkeypatch.setattr(settings, "watch_folder", str(folder))
    watcher_mod.scan_once()
    assert watcher_mod.last_reachable() is False
    assert watcher_mod.last_error()

    folder.mkdir()
    watcher_mod.scan_once()
    payload = _client().get("/api/watch/status").json()
    assert payload["reachable"] is True
    assert payload["last_error"] is None


def test_one_corrupt_pdf_does_not_make_the_folder_unreachable(drop_folder):
    """SCAN-LEVEL ONLY.

    A bad drop is a per-file 'failed' event and says nothing about the folder.
    Raising a folder-level alarm for one corrupt PDF would train an operator
    to ignore the alarm, which costs them the real outage later.
    """
    (drop_folder / "corrupt.pdf").write_bytes(b"not a pdf at all")
    watcher_mod.scan_once()
    watcher_mod.scan_once()
    assert len(events("failed")) == 1

    payload = _client().get("/api/watch/status").json()
    assert payload["reachable"] is True, "a bad file was blamed on the folder"
    assert payload["last_error"] is None
    # The failure is reported where it belongs, so nothing is lost by keeping
    # it out of last_error.
    assert payload["recent"][0]["outcome"] == "failed"


# ----------------------------------------------------- and it names nothing

def test_the_missing_folder_error_never_names_the_folder(tmp_path, monkeypatch):
    """`last_error` is shown to every caller, including the ones `folder` is
    withheld from. A message quoting the path would hand it straight back."""
    folder = tmp_path / SECRET / "drop"
    monkeypatch.setattr(settings, "watch_folder", str(folder))
    watcher_mod.scan_once()

    payload = _client().get("/api/watch/status").json()
    message = payload["last_error"]
    assert message
    assert SECRET not in message, f"the folder path leaked into last_error: {message!r}"
    assert str(folder) not in message
    assert str(tmp_path) not in message


def test_the_permission_error_never_leaks_the_path_the_os_puts_in_it(
        tmp_path, monkeypatch):
    """THE case the OS itself sabotages.

    `OSError` carries `filename`, so `str(exc)` for a denied share reads
    "[Errno 13] Permission denied: '<the whole path>'" - the path, the share
    name and often the host, in the field most likely to be printed on a
    screen. This test raises exactly that exception and asserts none of it
    survives into the payload, which is what stops anyone "improving" the
    message later by passing the exception text through.
    """
    folder = tmp_path / SECRET
    folder.mkdir()
    monkeypatch.setattr(settings, "watch_folder", str(folder))

    denied = PermissionError(13, "Permission denied", str(folder))
    assert SECRET in str(denied), "the exception under test must contain the path"

    def refuse(self):
        raise denied

    monkeypatch.setattr(Path, "iterdir", refuse)
    watcher_mod.scan_once()

    # Non-admin, because that is the caller this protects.
    _user("engineer", "Civil-Engineering", "discipline")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: req.headers.get("x-test-user") or None)
    payload = _client().get(
        "/api/watch/status", headers={"x-test-user": "engineer"}).json()

    assert payload["folder_name"] is None
    assert payload["reachable"] is False
    message = payload["last_error"]
    assert message
    assert SECRET not in message, f"the folder path leaked into last_error: {message!r}"
    assert str(folder) not in message
    assert "Errno" not in message, "the raw OSError text was passed through"
    assert "permission was denied" in message, (
        "the reason must still be stated - withholding the path is not "
        "withholding the explanation")


def test_turning_the_folder_off_clears_the_verdict_rather_than_freezing_it(
        tmp_path, monkeypatch):
    """Unconfiguring is not "still broken".

    An operator who removes a failing share from `.env` and restarts must see
    the feature reported as off, not as unreachable - a stale False would send
    them looking for a folder they have just deliberately taken away.
    """
    monkeypatch.setattr(settings, "watch_folder", str(tmp_path / "gone"))
    watcher_mod.scan_once()
    assert watcher_mod.last_reachable() is False

    monkeypatch.setattr(settings, "watch_folder", "")
    assert watcher_mod.scan_once()["state"] == "disabled"

    # ASSERTED ON THE WATCHER, not only on the payload. The off-payload is
    # built from literals - it has to be, since there is nothing to report -
    # so it would read `reachable: null` even for a watcher still holding last
    # week's False. The stale value would then be invisible here and visible
    # to the next thing that asks (a health check, a log line), which is
    # exactly how a fact ends up true in one place and false in another.
    assert watcher_mod.last_reachable() is None, "a stale verdict outlived the folder"
    assert watcher_mod.last_error() is None

    payload = _client().get("/api/watch/status").json()
    assert payload["enabled"] is False
    assert payload["reachable"] is None, "a stale unreachable verdict outlived the folder"
    assert payload["last_error"] is None


# ------------------------------------------------------------- the contract

def test_the_route_declares_a_typed_success_response():
    """The generated frontend types are only as good as this schema.

    Every 200 in this API was once documented as `string`, so the UI's types
    were guesses - `test_no_internal_leaks.py::test_every_endpoint_declares_a_
    typed_success_response` is the guard that exists because of it, and a
    route returning a bare dict trips it. This asserts the same property for
    THIS router specifically, so the regression is caught in the file that
    owns the route rather than in a whole-application sweep.

    It also asserts the two properties the panel actually depends on and that
    a bare `$ref` would not guarantee: that every nullable field is REQUIRED
    AND NULLABLE rather than optional-and-absent, and that `outcome` is the
    three-value union rather than a string. The frontend branches on null for
    every one of these; a type that says a field may be missing lets the UI
    treat absent and null as the same thing when only null can ever occur.
    """
    app = FastAPI()
    app.include_router(watch_router)
    spec = app.openapi()

    ok = spec["paths"]["/api/watch/status"]["get"]["responses"]["200"]
    schema = ok["content"]["application/json"]["schema"]
    assert "$ref" in schema, f"the success response is untyped: {schema}"

    status = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    fields = set(status["properties"])
    assert fields == {"enabled", "folder_name", "reachable", "last_error",
                      "last_scan_at", "interval_seconds", "recent"}
    assert set(status["required"]) == fields, (
        "every field is always present - the ones that can be unknown are "
        "null, not absent")

    for name in ("folder_name", "reachable", "last_error", "last_scan_at",
                 "interval_seconds"):
        variants = status["properties"][name].get("anyOf", [])
        assert {"type": "null"} in variants, (
            f"{name} can be null at runtime but the schema does not say so")

    event = spec["components"]["schemas"][
        status["properties"]["recent"]["items"]["$ref"].rsplit("/", 1)[-1]]
    assert set(event["properties"]) == {"filename", "outcome", "at", "detail"}
    assert event["properties"]["outcome"]["enum"] == [
        "ingested", "duplicate", "failed"], (
        "outcome must generate the union the frontend declares, not a string")
    assert {"type": "null"} in event["properties"]["detail"].get("anyOf", [])
    # And the host path is not in the contract at all, per row or otherwise.
    assert "source_path" not in event["properties"]


# ------------------------------------------------- the path itself, never

def test_only_the_last_segment_of_the_configured_path_is_ever_named():
    """`folder_name` is a NAME, not a location.

    The three spellings the backend can actually meet. The Windows one is the
    client's real deployment; the UNC one is the same share reached the other
    way, and it must yield the folder rather than `fileserver`, which would
    publish a hostname. Asserted through the pure function so every case is
    stated in one place, and through the route below so the payload is proven
    to use it.
    """
    from app.watch_api import folder_name

    assert folder_name(r"D:\project\Rag_chatbot\backend\data\watch-inbox") == "watch-inbox"
    assert folder_name("/srv/ragintel/backend/data/watch-inbox") == "watch-inbox"
    assert folder_name(r"\\fileserver\engineering\inbox") == "inbox"
    # The server name is the thing a UNC path leaks that a local path cannot.
    assert "fileserver" not in (folder_name(r"\\fileserver\engineering\inbox") or "")


def test_a_trailing_separator_still_names_the_folder():
    """The likeliest operator typo there is.

    Somebody pastes a share path into `.env` and it carries one extra
    character on the end. Answering null there would tell an administrator
    that NO folder is configured about a folder that is configured and
    working - so null must mean the value names nothing, never that a
    separator was typed one time too many.
    """
    from app.watch_api import folder_name

    assert folder_name("D:\\project\\data\\watch-inbox\\") == "watch-inbox"
    assert folder_name("/srv/ragintel/watch-inbox/") == "watch-inbox"
    assert folder_name("\\\\fileserver\\engineering\\inbox\\") == "inbox"
    # A doubled separator mid-path is the same defect and goes the same way.
    assert folder_name("D:\\project\\\\data\\watch-inbox") == "watch-inbox"


def test_a_value_that_names_no_folder_is_null_and_never_an_empty_string():
    """An empty string on a screen reads as a folder whose name is blank. It
    is not - it is a value that could not be derived, and this codebase spells
    that null."""
    from app.watch_api import folder_name

    assert folder_name("D:\\") is None                # drive root
    assert folder_name("/") is None                   # posix root
    assert folder_name("//") is None                  # a bare separator
    assert folder_name("D:") is None                  # a drive, not a folder
    assert folder_name("") is None
    assert folder_name("   ") is None
    # A UNC path with only a host names no folder, and the host is exactly
    # what must not be published. This case became REACHABLE when trailing
    # separators stopped yielding null: before the change it fell out for the
    # wrong reason, and a bare "\\\\fileserver" returned the machine name.
    assert folder_name("\\\\fileserver") is None
    assert folder_name("\\\\fileserver\\") is None


def test_the_admin_payload_carries_no_separator_character_at_all(
        drop_folder, monkeypatch):
    """A separator in that field means a path got through, whatever it is.

    Cheaper and stricter than matching path shapes: there is no legitimate
    value of `folder_name` containing one, so the character itself is the
    assertion.
    """
    _user("admin_user", "admin", "capability")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: req.headers.get("x-test-user") or None)

    payload = _client().get(
        "/api/watch/status", headers={"x-test-user": "admin_user"}).json()

    name = payload["folder_name"]
    assert name == "dropbox"
    assert "/" not in name and "\\" not in name


def test_no_part_of_the_parent_path_appears_anywhere_in_the_payload(
        drop_folder, monkeypatch):
    """The invariant the codebase-wide sweep asserts, held here too.

    THE PARENT IS PROVABLY AVAILABLE TO LEAK: `PARENT_DIR_MARKER` is a real
    directory the configured path passes through, and the assertion below
    first proves it is in that path. A test whose token was not actually in
    the configured value would pass against a route that published the whole
    thing.

    Scanned over the SERIALISED body rather than one key, because "the field
    was renamed" and "the value moved to another field" are both ways of
    continuing to publish the path while a test that only reads
    `folder_name` goes green.
    """
    _user("admin_user", "admin", "capability")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(lambda req: req.headers.get("x-test-user") or None)

    configured = settings.watch_folder
    assert PARENT_DIR_MARKER in configured, "the fixture no longer proves anything"

    (drop_folder / "spec.pdf").write_bytes(pdf_bytes())
    watcher_mod.scan_once()
    watcher_mod.scan_once()

    body = _client().get(
        "/api/watch/status", headers={"x-test-user": "admin_user"}).text

    assert PARENT_DIR_MARKER not in body, f"the parent directory leaked: {body[:300]}"
    assert configured not in body
    # Every segment ABOVE the folder itself, one by one - the drive, the
    # deployment root, and on a real machine the account name a home
    # directory carries.
    for segment in Path(configured).parent.parts:
        cleaned = segment.strip("/\\")
        if len(cleaned) > 2:      # skip "/" and a bare drive letter
            assert cleaned not in body, f"parent segment {cleaned!r} leaked"


def test_no_refusal_sentence_contains_a_path_either(drop_folder, monkeypatch):
    """`last_error` and every `detail` reach the same panel `folder_name` is
    withheld from. A sanitised field beside an unsanitised sentence is the
    leak moved, not closed."""
    sentences = [
        watcher_mod.OWNER_UNSET,
        watcher_mod.OWNER_UNKNOWN,
        watcher_mod.OWNER_HAS_NO_DISCIPLINE,
        watcher_mod.FolderWatcher._unreadable_because(
            PermissionError(13, "Permission denied", "/project/secret/inbox")),
        watcher_mod.FolderWatcher._unreadable_because(OSError("boom")),
    ]
    for sentence in sentences:
        assert "/" not in sentence and "\\" not in sentence, (
            f"a separator in an operator-facing sentence: {sentence!r}")
        assert "project" not in sentence
        assert "Errno" not in sentence

    # And the same for the missing-folder sentence, which is built at scan time.
    monkeypatch.setattr(settings, "watch_folder", str(drop_folder / "gone"))
    watcher_mod.scan_once()
    message = watcher_mod.last_error()
    assert message
    assert PARENT_DIR_MARKER not in message
    assert "/" not in message and "\\" not in message
