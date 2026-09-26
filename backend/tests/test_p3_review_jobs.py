"""P3: a review runs on the B11 job queue, not inside the request.

The request returns the queued run and its job; the worker runs it under the
REQUESTER'S grants, reports named progress, honours cancellation between
steps (removing what it had written), retries then poisons a failure with the
reason on the run, and is re-queued - not failed - after a crash. Synthetic
documents only. Mutations M880-M889.
"""
from __future__ import annotations

import json
import secrets

import pytest
from fastapi.testclient import TestClient

from app import (access, auth, comparison, datasheets, db, job_queue, keyword, review_jobs,
                 standards, submittal_review)
from app.config import config_version, settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"
W = "w-test"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "p3.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    monkeypatch.setattr(settings, "job_max_running", 1)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    keyword.ensure_schema()
    access.set_user_resolver(auth.resolve_user_id)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(doc_id, role, text):
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
                     "page_count,uploaded_at) VALUES (?,?,?,1,'/x','ready',1,?)",
                     (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", NOW))
        conn.execute("INSERT INTO document_classification (document_id,suggested_by,document_role)"
                     " VALUES (?,?,?)", (doc_id, "test", role))
        conn.execute("INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
                     "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'1',"
                     "'prose',?,1,?,1)", (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def _user(user_id, docs, admin=False):
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
                     " VALUES (?,?,?,'x',1,?)", (user_id, f"{user_id}@x", user_id, NOW))
        rid = f"r-{user_id}"
        conn.execute("INSERT INTO roles (id,name,description,kind,created_at) VALUES (?,?,'',?,?)",
                     (rid, rid, "discipline", NOW))
        conn.execute("INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)", (user_id, rid, NOW))
        if admin:
            conn.execute("INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                         " VALUES ('role_admin','admin','','capability',?)", (NOW,))
            adm = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()["id"]
            conn.execute("INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
                         (user_id, adm, NOW))
        for d in docs:
            conn.execute("INSERT INTO document_role_access (document_id,role_id,granted_at)"
                         " VALUES (?,?,?)", (d, rid, NOW))
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


@pytest.fixture
def world():
    std = _doc("std_api", "COMPANY_STANDARD", "Equipment noise level shall not exceed 90 dB(A).")
    sub = _doc("sub_pump", "CONTRACTOR_SUBMITTAL", "Pump shall comply with API 610. Noise level 95 dB(A)")
    with db.connect() as conn:
        conn.execute("UPDATE document_classification SET document_number = 'API 610' WHERE document_id = ?", (std,))
    standards.extract_requirements(std, allowed_document_ids=frozenset({std}))
    datasheets.create_fact(submittal_document_id=sub, chunk_id=f"{sub}-c1",
                           field_label="Noise level", raw_value="95", unit="dB(A)", page=1)
    admin = _user("adm", [std, sub], admin=True)
    return {"std": std, "sub": sub, "admin": admin, "scope": frozenset({std, sub})}


def _enqueue(w, user="adm"):
    return review_jobs.enqueue(w["sub"], allowed_document_ids=w["scope"], requested_by=user)


def _run_row(run_id):
    return dict(db.connect().execute("SELECT * FROM review_runs WHERE id = ?", (run_id,)).fetchone())


def _job(job_id):
    return dict(db.connect().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())


def _findings(run_id):
    return db.connect().execute("SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?",
                                (run_id,)).fetchone()[0]


def _audits(action):
    return [dict(r) for r in db.connect().execute("SELECT * FROM audit_events WHERE action = ?", (action,))]


def test_the_request_returns_a_queued_run_and_does_no_review_work(world):
    r = TestClient(app).post("/api/reviews/run", headers=world["admin"],
                             json={"submittal_document_id": world["sub"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "queued" and body["findings_total"] == 0
    assert body["job"]["state"] == "queued"
    assert (body["job"]["progress_done"], body["job"]["progress_total"]) == (0, 3)


def test_the_worker_runs_it_to_a_verdict_and_records_progress(world):
    run_id, job_id = _enqueue(world)
    assert review_jobs.claim_next(W) == job_id
    assert _run_row(run_id)["status"] == "running"
    assert review_jobs.run(job_id, W) == "done"
    assert _run_row(run_id)["status"] == "completed"
    job = _job(job_id)
    assert (job["state"], job["progress_done"], job["progress_label"]) == ("done", 3, "done")
    statuses = [r[0] for r in db.connect().execute(
        "SELECT compliance_status FROM review_findings WHERE review_run_id = ?", (run_id,))]
    assert comparison.NON_COMPLIANT in statuses
    assert [a["resource_id"] for a in _audits("job.done")] == [job_id]


def test_a_second_review_while_one_is_queued_is_refused(world):
    first, _ = _enqueue(world)
    with pytest.raises(review_jobs.ReviewAlreadyActive) as raised:
        _enqueue(world)
    assert raised.value.args[0] == first
    r = TestClient(app).post("/api/reviews/run", headers=world["admin"],
                             json={"submittal_document_id": world["sub"]})
    assert r.status_code == 409


def test_a_queued_review_is_cancelled_and_never_runs(world):
    run_id, job_id = _enqueue(world)
    r = TestClient(app).post(f"/api/jobs/{job_id}/cancel", headers=world["admin"])
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "cancelled"
    assert _run_row(run_id)["status"] == "cancelled"
    assert review_jobs.claim_next(W) is None


def test_a_running_review_stops_at_the_next_step_and_leaves_no_findings(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    # AN EARLIER ATTEMPT had written a finding before it failed; the retry is
    # the one being cancelled. What it leaves must not read as a result.
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_findings (id, document_id, review_run_id, category, severity,"
            " requirement, finding, required_action, governing_sources, citation_ids,"
            " unresolved_evidence, status, approval_status, escalation_level, created_at, updated_at)"
            " VALUES ('f-old', ?, ?, 'requirement_deviation', 'major', 'r', 'f', 'a', '[]', '[]',"
            " '[]', 'open', 'pending', 0, ?, ?)", (world["sub"], run_id, NOW, NOW))
    assert _findings(run_id) == 1
    # the cancel arrives while the job is claimed and running
    r = TestClient(app).post(f"/api/jobs/{job_id}/cancel", headers=world["admin"])
    assert r.status_code == 200 and r.json()["state"] == "running" and r.json()["cancel_requested"]
    assert review_jobs.run(job_id, W) == "cancelled"
    assert _run_row(run_id)["status"] == "cancelled" and _findings(run_id) == 0
    assert _job(job_id)["state"] == "cancelled"
    assert _audits("job.cancel_requested") and _audits("job.cancelled")


def test_a_failure_is_retried_then_poisoned_with_the_reason_on_the_run(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("synthetic comparison failure")
    monkeypatch.setattr(comparison, "run_comparison", boom)
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == job_queue.RETRYING
    assert _run_row(run_id)["status"] == "queued"
    monkeypatch.setattr(settings, "job_max_retries", 0)
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET state = 'running', claimed_by = ? WHERE id = ?", (W, job_id))
    assert review_jobs.run(job_id, W) == job_queue.POISONED
    run = _run_row(run_id)
    assert run["status"] == "failed" and "synthetic comparison failure" in run["refusal_reason"]


def test_the_review_runs_under_the_requesters_grants(world):
    """Grants revoked after the request: the worker must not read the sheet."""
    run_id, job_id = _enqueue(world)
    with db.connect() as conn:
        conn.execute("DELETE FROM document_role_access WHERE document_id = ?", (world["sub"],))
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) in (job_queue.RETRYING, job_queue.POISONED)
    assert _findings(run_id) == 0


def test_a_crashed_review_is_requeued_not_failed(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET claimed_at = '2000-01-01T00:00:00Z' WHERE id = ?", (job_id,))
    assert submittal_review.fail_orphaned_review_runs() == 0
    assert review_jobs.recover_stale() == 1
    assert _run_row(run_id)["status"] == "queued" and _job(job_id)["state"] == "queued"
    assert review_jobs.claim_next("w-new") == job_id
    assert review_jobs.run(job_id, "w-new") == "done"


def test_a_review_job_records_who_asked_and_which_code(world):
    _, job_id = _enqueue(world)
    job = _job(job_id)
    assert job["created_by"] == "adm" and job["code_version"] and job["config_version"] == config_version()
    assert [a["resource_id"] for a in _audits("job.queued")] == [job_id]


def test_the_job_api_shows_the_reviews_progress_only_to_readers(world):
    _, job_id = _enqueue(world)
    body = TestClient(app).get(f"/api/jobs/{job_id}", headers=world["admin"]).json()
    assert body["progress_total"] == 3 and body["review_run_id"]
    stranger = _user("stranger", [])
    assert TestClient(app).get(f"/api/jobs/{job_id}", headers=stranger).status_code == 404
