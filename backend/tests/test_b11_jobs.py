"""B11: background jobs you can trust - one per request, cancellable before
they start, bounded, attributable, audited, and visible only to those who may
read the document.

Synthetic documents only. Mutations M853-M862.
"""

from __future__ import annotations

import secrets
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import access, auth, db, job_queue, provenance, standards, submittal_review
from app.config import config_version, settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b11.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "job_max_running", 1)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    access.set_user_resolver(auth.resolve_user_id)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(doc_id: str) -> str:
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                     "status,uploaded_at) VALUES (?,?,?,1,'/dev/null','ready',?)",
                     (doc_id, f"{doc_id}.pdf", secrets.token_hex(16), NOW))
    return doc_id


def _user(user_id: str, role: str, docs=(), kind: str = "discipline") -> dict:
    conn = db.connect()
    with conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
                     " VALUES (?,?,?,'x',1,?)", (user_id, f"{user_id}@x", user_id, NOW))
        row = conn.execute("SELECT id FROM roles WHERE name = ?", (role,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO roles (id,name,description,kind,created_at) VALUES (?,?,'',?,?)",
                         (f"role_{role}", role, kind, NOW))
            rid = f"role_{role}"
        else:
            rid = row["id"]
        conn.execute("INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
                     (user_id, rid, NOW))
        for d in docs:
            conn.execute("INSERT OR IGNORE INTO document_role_access (document_id,role_id,granted_at)"
                         " VALUES (?,?,?)", (d, rid, NOW))
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


def _state(job_id: str) -> str:
    return db.connect().execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()["state"]


def _audits(action: str) -> list:
    return db.connect().execute(
        "SELECT * FROM audit_events WHERE action = ?", (action,)).fetchall()


# --------------------------------------------------------------- idempotency

def test_two_concurrent_requests_queue_one_job(monkeypatch):
    """The check and the insert were two steps: both requests saw nothing
    pending and both inserted. The pause below sits BETWEEN them, inside the
    transaction, so without the write lock the race is certain, not lucky."""
    doc = _doc("std1")
    real = provenance.code_version

    def slow(*modules):
        time.sleep(0.3)
        return real(*modules)
    monkeypatch.setattr(provenance, "code_version", slow)
    ids: list[str] = []
    errors: list[BaseException] = []

    def enqueue():
        try:
            ids.append(standards.enqueue_extraction(doc))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            db.reset_connection()
    threads = [threading.Thread(target=enqueue) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    assert len(set(ids)) == 1
    assert db.connect().execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1


def test_a_second_review_of_a_running_submittal_is_refused(monkeypatch):
    monkeypatch.setattr(submittal_review, "_extract_facts_if_none", lambda *a, **k: None)
    doc = _doc("sub1")
    scope = frozenset({doc})
    first = submittal_review.create_review_run(submittal_document_id=doc, allowed_document_ids=scope)
    with pytest.raises(submittal_review.ReviewAlreadyRunning) as raised:
        submittal_review.create_review_run(submittal_document_id=doc, allowed_document_ids=scope)
    assert raised.value.args[0] == first
    # once it has finished, a new one may start
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET status = 'completed' WHERE id = ?", (first,))
    assert submittal_review.create_review_run(submittal_document_id=doc, allowed_document_ids=scope)


# ----------------------------------------------------------------- provenance

def test_a_job_records_who_asked_and_which_code_and_settings():
    doc = _doc("std1")
    _user("adm", "admin", kind="capability")
    job_id = standards.enqueue_extraction(doc, actor={"id": "adm"})
    row = db.connect().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["created_by"] == "adm"
    assert row["code_version"] == provenance.code_version("standards", "tables", "requirements_3b")
    assert row["config_version"] == config_version()
    queued = _audits("job.queued")
    assert len(queued) == 1 and queued[0]["resource_id"] == job_id


# --------------------------------------------------------------- cancellation

def test_a_queued_job_can_be_cancelled_and_is_never_claimed():
    doc = _doc("std1")
    _user("adm", "admin", kind="capability")
    job_id = standards.enqueue_extraction(doc)
    assert job_queue.cancel(job_id, actor_user_id="adm") == (True, job_queue.CANCELLED)
    assert job_queue.cancel(job_id, actor_user_id="adm") == (False, job_queue.CANCELLED)
    assert _state(job_id) == "cancelled"
    assert standards.next_extraction_job("w-test") is None
    rows = _audits("job.cancelled")
    assert len(rows) == 1 and rows[0]["actor_user_id"] == "adm"


def test_a_running_job_is_not_reported_cancelled():
    doc = _doc("std1")
    job_id = standards.enqueue_extraction(doc)
    assert standards.next_extraction_job("w-test") == doc
    assert job_queue.cancel(job_id, actor_user_id="adm") == (False, "running")
    assert _state(job_id) == "running"
    assert _audits("job.cancelled") == []


# -------------------------------------------------------- bounded concurrency

def test_no_more_jobs_run_at_once_than_the_limit(monkeypatch):
    a, b = _doc("stdA"), _doc("stdB")
    standards.enqueue_extraction(a)
    standards.enqueue_extraction(b)
    first = standards.next_extraction_job("w-1")
    assert first in (a, b)
    assert standards.next_extraction_job("w-2") is None, "a second job ran past the limit"
    monkeypatch.setattr(settings, "job_max_running", 2)
    assert standards.next_extraction_job("w-2") == ({a, b} - {first}).pop()


def test_a_dead_workers_claim_does_not_hold_the_limit():
    a, b = _doc("stdA"), _doc("stdB")
    standards.enqueue_extraction(a)
    standards.enqueue_extraction(b)
    first = standards.next_extraction_job("w-1")
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET claimed_at = '2000-01-01T00:00:00Z' WHERE document_id = ?", (first,))
    assert standards.next_extraction_job("w-2") == ({a, b} - {first}).pop()


# ------------------------------------------------------------- audit of states

def test_poison_and_completion_are_audited(monkeypatch):
    monkeypatch.setattr(settings, "job_max_retries", 0)
    bad, good = _doc("stdBad"), _doc("stdGood")
    bad_job = standards.enqueue_extraction(bad)

    def boom(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(standards, "extract_requirements", boom)
    assert standards.run_extraction_job(bad, "w-1")["state"] == "poisoned"
    assert [r["resource_id"] for r in _audits("job.poisoned")] == [bad_job]

    good_job = standards.enqueue_extraction(good)
    monkeypatch.setattr(standards, "extract_requirements", lambda *a, **k: {"requirements": 1})
    monkeypatch.setattr(standards, "extract_table_values", lambda *a, **k: {"values": 0})
    assert standards.run_extraction_job(good, "w-1")["state"] == "done"
    assert [r["resource_id"] for r in _audits("job.done")] == [good_job]


# ------------------------------------------------------------ the job API

def test_the_job_api_shows_only_jobs_on_readable_documents():
    mine, theirs = _doc("stdMine"), _doc("stdTheirs")
    reader = _user("eng", "piping", docs=[mine])
    mine_job = standards.enqueue_extraction(mine)
    theirs_job = standards.enqueue_extraction(theirs)
    client = TestClient(app)
    listed = client.get("/api/jobs", headers=reader)
    assert listed.status_code == 200, listed.text
    assert [j["id"] for j in listed.json()["jobs"]] == [mine_job]
    assert client.get(f"/api/jobs/{mine_job}", headers=reader).status_code == 200
    hidden = client.get(f"/api/jobs/{theirs_job}", headers=reader)
    missing = client.get("/api/jobs/job_never", headers=reader)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()
    # a filter only narrows
    assert client.get(f"/api/jobs?document_id={theirs}", headers=reader).json()["jobs"] == []


def test_cancel_through_the_api_needs_an_admin_who_can_read_it():
    doc = _doc("std1")
    job_id = standards.enqueue_extraction(doc)
    reader = _user("eng", "piping", docs=[doc])
    admin = _user("adm", "admin", docs=[doc], kind="capability")
    client = TestClient(app)
    assert client.post(f"/api/jobs/{job_id}/cancel", headers=reader).status_code == 404
    assert _state(job_id) == "queued"
    r = client.post(f"/api/jobs/{job_id}/cancel", headers=admin)
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "cancelled"
    again = client.post(f"/api/jobs/{job_id}/cancel", headers=admin)
    assert again.status_code == 409 and "cancelled" in again.text
