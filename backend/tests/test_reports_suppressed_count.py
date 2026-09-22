"""`suppressed_count` tells a CALLER WITH AN IDENTITY that some of THEIR OWN
reports are hidden. It must never tell a caller with no identity anything.

WHAT WAS MEASURED (external tester, no bearer token, AUTH_MODE=demo_required):

    GET /api/reports  ->  {"reports": [], "suppressed_count": 13}

The rows were correctly withheld. The NUMBER was not, and 13 is a fact about
the corpus that an anonymous caller had no way to learn otherwise.

WHY THE NUMBER WAS WRONG, not merely unsafe. `list_reports` counted the
caller's own reports as

    [r for r in rows if r["owner_user_id"] == scope.user_id]

and an unidentified caller's `scope.user_id` is None, so every LEGACY report
row - written before ownership was stamped, owner NULL - compared equal and
was counted as the anonymous caller's own. That is the exact trap
`AccessScope.owns_conversation` is written to close for conversations ("no
identity -> no, whatever the row says"; the NULL-owner rows belong to the
admin capability and to nobody else). The count had its own second copy of
the ownership rule and that copy got the NULL case backwards.

So 0 here is not a comforting lie. Under the rule this codebase already
states, a caller with no identity owns no reports, and the number of THEIR
reports that are hidden is genuinely zero. The field stays an honest
measurement for everyone; it stops being a corpus census for a stranger.

These tests are red against the pre-fix code and each one was individually
mutation-proven by reverting the fix.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, chat, db, keyword, reports
from app.config import settings
from app.ingest import IngestionWorker
from app.main import app

VIBRATION = [
    "5.3.2 Vibration Limits",
    "Vibration limits per API 610 shall not exceed 3.0 mm/s RMS measured at the",
    "bearing housing of pump P-101A during continuous operation at rated flow,",
    "and any exceedance shall be reported to the area engineer before the pump",
    "is returned to service under the procedure given in this specification.",
]
MATERIALS = [
    "7.1 Materials of Construction",
    "Casing material shall be ASTM A216 WCB with an impeller of CA6NM and a",
    "shaft of AISI 4140 for all centrifugal pumps in hydrocarbon service, and",
    "alternative materials require written approval from the principal engineer.",
]
VIBRATION_Q = "what are the vibration limits for pump P-101A"
MATERIALS_Q = "what is the casing material for centrifugal pumps"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield
    db.reset_connection()


def ingest(name="spec.pdf", blocks=(VIBRATION, MATERIALS)) -> str:
    path = settings.data_dir / name
    doc = pymupdf.open()
    for block in blocks:
        page = doc.new_page()
        for i, line in enumerate(block):
            page.insert_text((72, 100 + i * 16), line)
    doc.save(str(path))
    doc.close()
    with open(path, "rb") as fh:
        doc_id = TestClient(app).post(
            "/api/documents", files={"file": (name, fh, "application/pdf")}
        ).json()["document"]["id"]
    IngestionWorker().process(doc_id)
    return doc_id


def answered_message(doc_id: str, question: str, owner: str | None = None) -> dict:
    """An answer that can cite ONE document, because that is all it was shown.

    Restricting `allowed_document_ids` to a single id is what makes each
    report's citation set deterministic, so revoking one grant suppresses
    exactly one report and the expected count is a fact rather than a guess.
    """
    conv = chat.create_conversation(owner_user_id=owner)
    result = chat.ask(conv["id"], question, tier="extract",
                      allowed_document_ids=frozenset({doc_id}))
    assert result["answer_type"] == "extract", result.get("reason")
    return result["assistant_message"]


def user(email: str, role_id: str, doc_ids) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn = db.connect()
    uid = f"user_{email.split('@')[0]}"
    with conn:
        conn.execute("INSERT OR IGNORE INTO roles (id, name, description, created_at) "
                     "VALUES (?, ?, '', ?)", (role_id, role_id, now))
        conn.execute("INSERT INTO users (id, email, display_name, password_hash, "
                     "is_active, created_at) VALUES (?, ?, ?, 'x', 1, ?)",
                     (uid, email, email, now))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id, granted_at) "
                     "VALUES (?, ?, ?)", (uid, role_id, now))
        for d in doc_ids:
            conn.execute("INSERT INTO document_role_access (document_id, role_id, "
                         "granted_at) VALUES (?, ?, ?)", (d, role_id, now))
    return uid


def owner_of(report_id: str):
    return db.connect().execute(
        "SELECT owner_user_id FROM reports WHERE id = ?", (report_id,)
    ).fetchone()["owner_user_id"]


def report_count() -> int:
    return db.connect().execute("SELECT COUNT(*) FROM reports").fetchone()[0]


def listing(uid: str | None, monkeypatch) -> dict:
    """GET /api/reports as `uid`, or as nobody when `uid` is None."""
    monkeypatch.setattr(access, "_resolve_user_id", lambda request: uid)
    return TestClient(app).get("/api/reports").json()


def test_report_list_supports_bounded_pagination_and_sort(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    response = TestClient(app).get("/api/reports", params={
        "limit": 10, "offset": 0, "sort": "question", "direction": "asc",
        "q": "pump",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["reports"] == []
    assert body["total_matching"] == 0
    assert body["limit"] == 10
    assert body["offset"] == 0


def revoke(doc_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM document_role_access WHERE document_id = ?", (doc_id,))


# --------------------------------------------------------------- the defect


def test_an_unidentified_caller_is_told_nothing_about_how_many_reports_exist(monkeypatch):
    """THE REPORTED DEFECT. Empty list, and no number attached to it.

    The report generated here is a legacy row - owner NULL, exactly the shape
    of the rows in the demo database - because it was generated under
    `unrestricted_scope`, which has no user to stamp. Before the fix an
    anonymous caller counted every such row as its own and the response said
    how many reports exist.
    """
    doc = ingest()
    rec = reports.generate(answered_message(doc, VIBRATION_Q)["id"],
                           access.unrestricted_scope())
    assert owner_of(rec["id"]) is None, "fixture: this must be a legacy NULL-owner row"
    assert report_count() == 1

    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    body = listing(None, monkeypatch)

    assert body["reports"] == [], "the rows were never the problem"
    # A stranger learns nothing. 0 is true of them: they own no reports, so
    # none of theirs is hidden.
    assert body.get("suppressed_count", 0) == 0, (
        "an unauthenticated caller was told how many reports exist: "
        f"{body.get('suppressed_count')} of {report_count()} in the database"
    )


def test_the_honesty_affordance_survives_for_a_signed_in_user(monkeypatch):
    """The field exists so a REAL user is not shown a silently short list.

    Two of this user's own reports, one cited document revoked: one report is
    gone and the user is told that one is gone, without being told which.
    """
    doc_a = ingest("a.pdf", (VIBRATION,))
    doc_b = ingest("b.pdf", (MATERIALS,))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    uid = user("a@x.test", "role_a", [doc_a, doc_b])
    scope = access.scope_for_user(uid)
    hidden = reports.generate(answered_message(doc_a, VIBRATION_Q, uid)["id"], scope)
    kept = reports.generate(answered_message(doc_b, MATERIALS_Q, uid)["id"], scope)
    assert owner_of(hidden["id"]) == uid and owner_of(kept["id"]) == uid

    revoke(doc_a)
    body = listing(uid, monkeypatch)

    assert [r["id"] for r in body["reports"]] == [kept["id"]]
    assert body["suppressed_count"] == 1
    # THAT something is hidden, never WHAT.
    assert hidden["id"] not in TestClient(app).get("/api/reports").text


def test_a_user_suppressed_from_nothing_is_told_zero(monkeypatch):
    """Zero, present, and the same shape a stranger gets. A user who can see
    everything they own must not see a warning about a shortfall that is not
    there."""
    doc = ingest()
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    uid = user("a@x.test", "role_a", [doc])
    rec = reports.generate(answered_message(doc, VIBRATION_Q, uid)["id"],
                           access.scope_for_user(uid))

    body = listing(uid, monkeypatch)

    assert [r["id"] for r in body["reports"]] == [rec["id"]]
    assert body.get("suppressed_count", 0) == 0
    # consistent with the stranger's answer: same field, same safe value
    assert body.get("suppressed_count", 0) == listing(None, monkeypatch).get(
        "suppressed_count", 0)


def test_the_count_can_never_exceed_the_reports_that_exist(monkeypatch):
    """A hidden-count larger than the corpus would be a leak wearing the
    shape of a bug. Checked for a stranger, for the owner, and for a signed-in
    user who owns nothing at all - the last is the case that inherited the
    NULL-owner rows before the fix."""
    doc_a = ingest("a.pdf", (VIBRATION,))
    doc_b = ingest("b.pdf", (MATERIALS,))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    owner = user("a@x.test", "role_a", [doc_a, doc_b])
    stranger = user("b@x.test", "role_b", [])
    reports.generate(answered_message(doc_a, VIBRATION_Q, owner)["id"],
                     access.scope_for_user(owner))
    # a legacy row nobody owns, alongside the owned one
    reports.generate(answered_message(doc_b, MATERIALS_Q)["id"],
                     access.unrestricted_scope())
    revoke(doc_a)

    total = report_count()
    assert total == 2
    for who in (None, owner, stranger):
        body = listing(who, monkeypatch)
        count = body.get("suppressed_count", 0)
        assert 0 <= count <= total, f"{who!r} was told {count} of {total}"
        assert count + len(body["reports"]) <= total, (
            "shown plus hidden exceeds what exists")
    # and specifically: neither the stranger nor the anonymous caller inherits
    # the report they do not own
    assert listing(stranger, monkeypatch).get("suppressed_count", 0) == 0
    assert listing(None, monkeypatch).get("suppressed_count", 0) == 0
    # the owner keeps a true measurement: their one report is hidden
    assert listing(owner, monkeypatch)["suppressed_count"] == 1
