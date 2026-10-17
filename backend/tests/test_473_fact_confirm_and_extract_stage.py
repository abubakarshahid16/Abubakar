"""#473 (audit D04, DB-M3): a confirm path writes `submittal_facts.confirmed_by`;
`extract.py` takes its own stage's job.

What was wrong: the column had readers (`comparison.low_trust_reason` trusts a
confirmed value whatever read it; the facts reader never supersedes one) and
no writer, so no value could ever be confirmed. And `extract_document` took
the document's NEWEST job whatever its stage, so with a later-stage job on
the row (a failed facts read, a review) it wrote its page progress and
'done' onto that job. Invented documents and values only.
"""
from __future__ import annotations

import secrets
import uuid

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import access, auth, comparison, db, extract, submittal_review
from app.config import settings
from app.main import app
from tests.test_crs_submittal_delete_orphan_guard import (  # noqa: F401 - fixture
    NOW, temp_storage)


def _engineer(monkeypatch, *, documents: tuple[str, ...]) -> tuple[TestClient, dict]:
    """A real, signed-in, non-admin engineer who may read `documents`."""
    with db.connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (id,email,display_name,password_hash,"
            "is_active,created_at) VALUES ('eng','eng@e.test','Eng',?,1,?)",
            (auth._hasher.hash("engineer-pass"), NOW))
        conn.execute("INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                     " VALUES ('role_eng','eng','engineers','discipline',?)", (NOW,))
        conn.execute("INSERT OR IGNORE INTO user_roles (user_id,role_id,granted_at)"
                     " VALUES ('eng','role_eng',?)", (NOW,))
        for doc in documents:
            conn.execute("INSERT OR IGNORE INTO document_role_access (document_id,role_id,"
                         "permission,granted_at) VALUES (?,'role_eng','read',?)", (doc, NOW))
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    access.set_user_resolver(auth.resolve_user_id)
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"email": "eng@e.test", "password": "engineer-pass"})
    assert login.status_code == 200, login.text
    return client, {"Authorization": f"Bearer {login.json()['token']}"}


def _document(doc_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES (?,?,?,1,?,'ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", f"{doc_id}.pdf", NOW))


def _fact(doc_id: str, *, superseded: bool = False) -> str:
    fact_id = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO submittal_facts (id, submittal_document_id, field_name, field_value,"
            " extraction_method, validation_state, superseded_at, created_at, updated_at)"
            " VALUES (?,?,'design pressure','3.5','model','needs_engineer_review',?,?,?)",
            (fact_id, doc_id, NOW if superseded else None, NOW, NOW))
    return fact_id


def _stored(fact_id: str) -> dict:
    return dict(db.connect().execute("SELECT * FROM submittal_facts WHERE id = ?",
                                     (fact_id,)).fetchone())


# ------------------------------------------------------------ the confirm path

def test_a_signed_in_engineer_confirms_a_value_and_the_comparison_then_trusts_it(monkeypatch):
    _document("sub")
    fact_id = _fact("sub")
    client, headers = _engineer(monkeypatch, documents=("sub",))
    before = _stored(fact_id)
    assert before["confirmed_by"] is None
    assert comparison.low_trust_reason(before), "the fixture is not a low-trust value"

    r = client.post(f"/api/reviews/facts/{fact_id}/confirm", headers=headers)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confirmed_by"] == "eng" and body["confirmed_at"]
    assert body["fact_id"] == fact_id and body["submittal_document_id"] == "sub"
    after = _stored(fact_id)
    assert after["confirmed_by"] == "eng" and after["confirmed_at"] == body["confirmed_at"]
    assert comparison.low_trust_reason(after) is None, "a confirmed value is still distrusted"
    trail = db.connect().execute(
        "SELECT actor_user_id, detail FROM audit_events WHERE action = 'fact.confirmed'"
        " AND resource_id = ?", (fact_id,)).fetchall()
    assert [tuple(t) for t in trail] == [("eng", "document=sub")]
    # Ids only on the trail: never the value or its text.
    assert "3.5" not in (trail[0]["detail"] or "")


def test_confirming_twice_keeps_the_first_name_and_time(monkeypatch):
    _document("sub")
    fact_id = _fact("sub")
    client, headers = _engineer(monkeypatch, documents=("sub",))
    first = client.post(f"/api/reviews/facts/{fact_id}/confirm", headers=headers).json()
    with db.connect() as conn:
        conn.execute("UPDATE submittal_facts SET confirmed_at = '2026-01-01T00:00:00Z' WHERE id = ?",
                     (fact_id,))
    second = client.post(f"/api/reviews/facts/{fact_id}/confirm", headers=headers)
    assert second.status_code == 200
    assert second.json()["confirmed_at"] == "2026-01-01T00:00:00Z" != first["confirmed_at"]
    assert db.connect().execute("SELECT COUNT(*) FROM audit_events WHERE action = 'fact.confirmed'"
                                ).fetchone()[0] == 1


def test_nobody_confirms_anonymously_in_either_auth_mode(monkeypatch):
    """`confirmed_by` NULL means "not confirmed": an unsigned call must not
    pretend otherwise, even under the development mode that lets anonymous
    callers read everything."""
    _document("sub")
    fact_id = _fact("sub")
    r = TestClient(app).post(f"/api/reviews/facts/{fact_id}/confirm")  # AUTH_MODE=disabled
    assert r.status_code == 401, r.text
    assert r.json()["detail"]["code"] == "unauthenticated"
    client, _headers = _engineer(monkeypatch, documents=("sub",))
    assert client.post(f"/api/reviews/facts/{fact_id}/confirm").status_code == 401
    assert _stored(fact_id)["confirmed_by"] is None
    with pytest.raises(ValueError):
        submittal_review.confirm_fact(fact_id, allowed_document_ids=frozenset({"sub"}),
                                      confirmed_by="")


def test_a_fact_on_a_submittal_the_caller_may_not_read_is_404_like_a_missing_one(monkeypatch):
    _document("sub")
    _document("theirs")
    hidden = _fact("theirs")
    client, headers = _engineer(monkeypatch, documents=("sub",))
    for fact_id in (hidden, "no-such-fact"):
        r = client.post(f"/api/reviews/facts/{fact_id}/confirm", headers=headers)
        assert r.status_code == 404, r.text
    assert _stored(hidden)["confirmed_by"] is None


def test_a_superseded_fact_is_refused_by_name_not_confirmed(monkeypatch):
    _document("sub")
    old = _fact("sub", superseded=True)
    client, headers = _engineer(monkeypatch, documents=("sub",))
    r = client.post(f"/api/reviews/facts/{old}/confirm", headers=headers)
    assert r.status_code == 409, r.text
    assert "re-read" in r.json()["detail"]["message"]
    assert _stored(old)["confirmed_by"] is None


# --------------------------------------------------- extract takes its own job

def _uploaded_pdf(tmp_path) -> str:
    path = tmp_path / "pages.pdf"
    pdf = pymupdf.open()
    for i in (1, 2):
        pdf.new_page().insert_text((72, 100), f"Section {i}.0 Heading", fontsize=13)
    pdf.save(str(path))
    pdf.close()
    with path.open("rb") as fh:
        r = TestClient(app).post("/api/documents",
                                 files={"file": (path.name, fh, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()["document"]["id"]


def test_extract_writes_its_progress_on_the_extract_job_not_the_newest_job(tmp_path):
    doc_id = _uploaded_pdf(tmp_path)
    conn = db.connect()
    extract_job = conn.execute("SELECT id FROM jobs WHERE document_id = ? AND stage = 'extract'",
                               (doc_id,)).fetchone()["id"]
    # A LATER job of another stage, the way `ingest` records a failed facts
    # read: newer `started_at`, nothing to do with pages.
    with conn:
        conn.execute("INSERT INTO jobs (id, document_id, stage, state, error_code, started_at,"
                     " updated_at) VALUES ('facts-job', ?, 'extract_facts', 'failed',"
                     " 'extract_facts_failed', '2099-01-01T00:00:00Z', '2099-01-01T00:00:00Z')",
                     (doc_id,))

    result = extract.extract_document(doc_id)

    assert result["pages_extracted"] == 2 and result.get("error") is None
    mine = dict(conn.execute("SELECT * FROM jobs WHERE id = ?", (extract_job,)).fetchone())
    other = dict(conn.execute("SELECT * FROM jobs WHERE id = 'facts-job'").fetchone())
    assert (mine["stage"], mine["state"], mine["pages_done"]) == ("chunk", "done", 2)
    assert (other["stage"], other["state"], other["pages_done"]) == ("extract_facts", "failed", 0)


def test_extract_with_no_job_of_its_stage_is_a_named_failure(tmp_path):
    doc_id = _uploaded_pdf(tmp_path)
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET stage = 'review' WHERE document_id = ?", (doc_id,))
    with pytest.raises(ValueError, match="no extract job"):
        extract.extract_document(doc_id)
