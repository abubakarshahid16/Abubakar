"""#478 / #608: GET /api/risks only reads. Detection is a background job.

Invented data. The 100,000 findings are all old and open, so the old GET
would have tried to create a risk and send an email for each of them.
"""
from __future__ import annotations

import hashlib
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import db, deliverables, notifications, review, risks
from app.config import settings


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "w7risks.sqlite")
    monkeypatch.setattr(settings, "startup_warmup", False)
    db.reset_connection()
    db.init_db()
    deliverables.ensure_schema()
    review.ensure_schema()
    risks.ensure_schema()
    with db.connect() as con:
        con.execute("INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
                    " VALUES ('doc','review.pdf',?,1,'x','ready','2020-01-01')",
                    (hashlib.sha256(b"doc").hexdigest(),))
    sent = []
    monkeypatch.setattr(notifications, "send_email", lambda **kw: sent.append(kw) or True)
    yield sent
    db.reset_connection()


def _findings(n, *, deviation=False, document_id="doc", id_prefix="f"):
    rows = [(f"{id_prefix}{i:06d}", document_id, "requirement_deviation" if deviation else "other",
             "major", "r", "f", "a",
             json.dumps(["missing citation"]) if deviation else "[]", "open",
             "2020-01-01", "2020-01-01") for i in range(n)]
    with db.connect() as con:
        con.executemany(
            "INSERT INTO review_findings (id, document_id, category, severity, requirement, finding,"
            " required_action, unresolved_evidence, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)


def _document(doc_id):
    with db.connect() as con:
        con.execute("INSERT INTO documents(id,filename,sha256,size_bytes,stored_path,status,uploaded_at)"
                    " VALUES (?,?,?,1,'x','ready','2020-01-01')",
                    (doc_id, f"{doc_id}.pdf", hashlib.sha256(doc_id.encode()).hexdigest()))


def _client():
    from app.main import app
    return TestClient(app, base_url="http://127.0.0.1")


def test_get_risks_writes_nothing_and_emails_nothing_on_100000_findings(world, monkeypatch):
    _findings(100_000)
    spied = []
    for name in ("detect_automatic_risks", "run_detection", "create", "_insert_many"):
        real = getattr(risks, name)
        monkeypatch.setattr(risks, name, lambda *a, _n=name, _r=real, **k: spied.append(_n) or _r(*a, **k))
    con = db.connect()
    before = con.execute("SELECT COUNT(*) FROM risks").fetchone()[0]
    version = con.execute("PRAGMA data_version").fetchone()[0]
    start = time.perf_counter()
    r = _client().get("/api/risks")
    took = time.perf_counter() - start
    assert r.status_code == 200 and r.json()["risks"] == [] and r.json()["total"] == 0
    assert took < 2.0, f"GET /api/risks took {took:.2f}s on 100,000 findings"
    assert spied == [], f"GET /api/risks ran {spied}"
    assert world == [], "GET /api/risks sent an email"
    assert con.execute("SELECT COUNT(*) FROM risks").fetchone()[0] == before == 0
    assert con.execute("PRAGMA data_version").fetchone()[0] == version, "something committed during the GET"


def test_detection_creates_each_risk_once_and_sends_one_digest(world, monkeypatch):
    """A10/#924: 300 findings on ONE document are one review risk and one
    compliance risk, not 600 - the explosion that made the live risks table
    147,770 rows, all open, for 143,558 findings."""
    monkeypatch.setattr(settings, "smtp_enabled", True)
    _findings(300, deviation=True)                 # one document: one review risk, one compliance risk
    first = risks.run_detection()
    assert first["status"] == "ok" and first["created"] == 2
    assert first["by_type"] == {"review": 1, "compliance": 1}
    assert len(world) == 1, f"{len(world)} emails for 2 risks"
    assert first["digest"] == "sent"
    assert "2 new" in world[0]["subject"]
    rows = db.connect().execute("SELECT description FROM risks ORDER BY risk_type").fetchall()
    assert all("300" in row["description"] for row in rows), rows
    again = risks.run_detection()
    assert again["created"] == 0 and again["digest"] == "none"
    assert len(world) == 1
    assert db.connect().execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 2


def test_the_digest_is_rate_limited_not_one_per_run(world, monkeypatch):
    """Each batch lands on its OWN document (A10/#924: a second batch on the
    SAME document would be deduplicated into the first batch's still-open
    aggregate, never minting a second risk - this test is about the digest's
    own rate limit, not that dedup, so it gives each batch a document the
    aggregate has not already covered)."""
    monkeypatch.setattr(settings, "smtp_enabled", True)
    monkeypatch.setattr(settings, "risk_digest_min_interval_seconds", 3600)
    _findings(5)
    assert risks.run_detection()["digest"] == "sent"
    _document("doc2")
    _findings(5, document_id="doc2", id_prefix="x")
    second = risks.run_detection()
    assert second["created"] == 1 and second["digest"] == "rate_limited"
    assert len(world) == 1
    monkeypatch.setattr(settings, "risk_digest_min_interval_seconds", 0)
    _document("doc3")
    _findings(3, document_id="doc3", id_prefix="g")
    assert risks.run_detection()["digest"] == "sent" and len(world) == 2


def test_nothing_is_emailed_when_smtp_is_off(world):
    _findings(10)
    out = risks.run_detection()
    assert out["created"] == 1 and out["digest"] == "disabled" and world == []


def test_detection_asks_the_database_a_fixed_number_of_questions(world):
    def statements(n):
        db.reset_connection()
        db.init_db()
        with db.connect() as con:
            con.execute("DELETE FROM review_findings")
            con.execute("DELETE FROM risks")
        _findings(n, deviation=True)
        seen = []
        con = db.connect()
        con.set_trace_callback(seen.append)
        risks.detect_automatic_risks()
        con.set_trace_callback(None)
        return len([q for q in seen if q.lstrip().upper().startswith('SELECT')])
    few, many = statements(20), statements(2000)
    assert many <= few + 2, f"{few} SELECTs for 20 findings, {many} for 2,000"


def test_two_detection_runs_at_once_run_once(world):
    _findings(10)
    assert risks._detect_lock.acquire(blocking=False)
    try:
        assert risks.run_detection()["status"] == "already_running"
    finally:
        risks._detect_lock.release()


def test_the_admin_trigger_runs_detection_and_returns_counts(world):
    _findings(4)
    r = _client().post("/api/risks/detect")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["created"] == 1
    assert _client().get("/api/risks").json()["risks"].__len__() == 1


def test_a_non_admin_cannot_trigger_detection(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "demo_required")
    _findings(4)
    r = _client().post("/api/risks/detect")
    assert r.status_code in (401, 404)
    assert db.connect().execute("SELECT COUNT(*) FROM risks").fetchone()[0] == 0


def test_the_background_job_is_off_in_tests_and_on_by_interval(monkeypatch):
    monkeypatch.setattr(settings, "startup_warmup", False)
    assert risks.start_background_detection() is None
    monkeypatch.setattr(settings, "startup_warmup", True)
    monkeypatch.setattr(settings, "risk_detection_interval_seconds", 0)
    assert risks.start_background_detection() is None
    monkeypatch.setattr(settings, "risk_detection_interval_seconds", 3600)
    thread = risks.start_background_detection()
    try:
        assert thread is not None and thread.is_alive()
    finally:
        risks.stop_background_detection()
        thread.join(5)


def test_reading_deliverables_does_not_repair_owners(world):
    """The owner sync used to run inside ensure_schema on EVERY call, so every
    deliverables GET wrote. It now runs in create and update, with the change."""
    # Settle the memoised table check first (another module's DDL in the
    # fixture changes the schema version once, which re-runs the bootstrap).
    deliverables.ensure_schema()
    deliverables.ensure_schema()
    with db.connect() as con:
        con.execute("INSERT INTO users(id, email, display_name, password_hash, created_at)"
                    " VALUES ('u1','u1@example.test','U1','x','2020-01-01')")
        con.execute("INSERT INTO deliverables(id,wbs_code,title,deliverable_type,revision,status,owner_user_id,"
                    "created_at,updated_at,org_wide) VALUES ('d1','1','T','report','0','planned','u1',"
                    "'2020-01-01','2020-01-01',1)")
    deliverables.ensure_schema()
    deliverables.list_items()
    count = lambda: db.connect().execute(  # noqa: E731
        "SELECT COUNT(*) FROM deliverable_stakeholders").fetchone()[0]
    assert count() == 0, "a read wrote a stakeholder row"
    deliverables.update("d1", {"owner_user_id": "u1"})
    assert count() == 1, "an owner change must make the owner a stakeholder"


def test_get_reminders_creates_no_events_and_sends_nothing(world, monkeypatch):
    monkeypatch.setattr(settings, "smtp_enabled", True)
    deliverables.create({"wbs_code": "9.1", "title": "Late", "deliverable_type": "report",
                         "due_date": "2020-01-01"}, created_by=None)
    r = _client().get("/api/management/reminders")
    assert r.status_code == 200
    assert r.json()["reminders"] == [] and r.json()["total"] == 0
    assert world == []
    assert deliverables.generate_reminders() == 1
    assert len(_client().get("/api/management/reminders").json()["reminders"]) == 1
