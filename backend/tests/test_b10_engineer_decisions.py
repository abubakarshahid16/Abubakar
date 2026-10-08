"""B10: an engineer's decision on a finding is the engineer's, and only theirs.

Before this, `ReviewFindingUpdate` accepted `approved_by` / `approved_at` from
the request body - an approval could be recorded in anybody's name - and
`ReviewFindingCreate` accepted `approval_status` / `disposition`, so a finding
could be CREATED already accepted: no engineer ever acted on it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, db, submittal_review
from app.config import settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b10.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute("INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,"
                     "status,page_count,uploaded_at) VALUES ('d1','d1.pdf','s1',1,'/x','ready',1,?)",
                     (NOW,))
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,created_at)"
                     " VALUES ('eng-1','e@x','Eng','h',?)", (NOW,))
        conn.execute("INSERT INTO roles (id,name,description,kind,created_at)"
                     " VALUES ('r1','r1','r','discipline',?)", (NOW,))
        conn.execute("INSERT INTO user_roles (user_id,role_id,granted_at) VALUES ('eng-1','r1',?)", (NOW,))
        conn.execute("INSERT INTO document_role_access (document_id,role_id,granted_at)"
                     " VALUES ('d1','r1',?)", (NOW,))
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _as(user_id):
    access.set_user_resolver(lambda request: user_id)
    return TestClient(app)


BASE = {"document_id": "d1", "category": "requirement_deviation", "severity": "major",
        "requirement": "The noise level shall not exceed a stated limit.",
        "finding": "A higher value was submitted.", "required_action": "Revise."}


def _created() -> str:
    r = _as("eng-1").post("/api/reviews/findings", json=BASE)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_a_finding_cannot_be_created_already_accepted():
    client = _as("eng-1")
    assert client.post("/api/reviews/findings",
                       json={**BASE, "approval_status": "accepted"}).status_code == 422
    assert client.post("/api/reviews/findings",
                       json={**BASE, "disposition": "accepted"}).status_code == 422
    # the control: an ordinary creation is accepted, and is pending
    r = client.post("/api/reviews/findings", json=BASE)
    assert r.status_code == 200 and r.json()["approval_status"] == "pending"
    assert r.json()["approved_by"] is None


def test_an_approval_names_the_caller_never_the_body():
    fid = _created()
    r = _as("eng-1").patch(f"/api/reviews/findings/{fid}",
                           json={"approval_status": "accepted", "approved_by": "somebody-else",
                                 "approved_at": "2000-01-01T00:00:00Z"})
    assert r.status_code == 200, r.text
    assert r.json()["approval_status"] == "accepted"
    assert r.json()["approved_by"] == "eng-1"
    assert r.json()["approved_at"] and not r.json()["approved_at"].startswith("2000")


def test_a_disposition_is_also_signed_by_the_caller():
    fid = _created()
    r = _as("eng-1").patch(f"/api/reviews/findings/{fid}", json={"disposition": "rejected"})
    assert r.status_code == 200, r.text
    assert r.json()["approved_by"] == "eng-1"


def test_the_decision_is_in_the_finding_history():
    fid = _created()
    client = _as("eng-1")
    client.patch(f"/api/reviews/findings/{fid}", json={"approval_status": "rejected"})
    r = client.get(f"/api/reviews/findings/{fid}/history")
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    decided = [e for e in events if e["changes"].get("approval_status") == "rejected"]
    assert decided and decided[0]["actor_user_id"] == "eng-1"
    assert decided[0]["changes"]["approved_by"] == "eng-1"


# ------------------------------------------------ audit is part of the decision

import json  # noqa: E402
import uuid  # noqa: E402

from app import comparison, crs_export  # noqa: E402


def _run(recommended="Manual Review Required") -> str:
    run_id = str(uuid.uuid4())
    outcome = json.dumps({"recommended_code": recommended, "reason": "a reason"}) if recommended else None
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,refusal_reason,"
                     "created_at,updated_at) VALUES (?,'d1','completed',?,?,?)",
                     (run_id, outcome, NOW, NOW))
    return run_id


def _audits(action):
    return db.connect().execute(
        "SELECT * FROM audit_events WHERE action = ?", (action,)).fetchall()


def test_a_code_decision_is_audited_with_the_engineer():
    run_id = _run()
    r = _as("eng-1").post(f"/api/reviews/runs/{run_id}/code",
                          json={"code": "Manual Review Required"})
    assert r.status_code == 200, r.text
    rows = _audits("review.code_recorded")
    assert len(rows) == 1 and rows[0]["actor_user_id"] == "eng-1"


def test_a_code_decision_whose_audit_fails_is_not_recorded(monkeypatch):
    run_id = _run()

    def broken(*a, **k):
        raise RuntimeError("audit table unwritable")
    monkeypatch.setattr(comparison, "_audit", broken)
    with pytest.raises(RuntimeError):
        comparison.record_engineer_code(
            run_id, code="Manual Review Required", reviewer="eng-1",
            allowed_document_ids=frozenset({"d1"}), actor={"id": "eng-1"})
    row = db.connect().execute(
        "SELECT engineer_final_code FROM review_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["engineer_final_code"] is None, "a decision stood with no audit row"


def test_a_pair_rejection_is_audited_once():
    req = {"id": "req-9", "standard_document_id": "d1", "clause": "1.1",
           "requirement_text": "A value shall not exceed a limit."}
    fact = {"id": "fact-9", "submittal_document_id": "d1", "field_name": "value"}
    comparison.reject_pair(req, fact, rejected_by="eng-1", reason="different equipment")
    comparison.reject_pair(req, fact, rejected_by="eng-1", reason="again")
    rows = _audits("review.pair_rejected")
    assert len(rows) == 1
    assert rows[0]["actor_user_id"] == "eng-1" and rows[0]["resource_id"] == "req-9"


def _preview(run_id):
    r = _as("eng-1").get(f"/api/reviews/runs/{run_id}/crs/preview")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_crs_says_an_ai_code_is_not_yet_an_engineers_decision():
    run_id = _run()
    assert _preview(run_id)["recommended_code_status"] == crs_export.CODE_NOT_YET_DECIDED


def test_the_crs_says_an_engineer_decided_the_code():
    run_id = _run()
    assert _as("eng-1").post(f"/api/reviews/runs/{run_id}/code",
                             json={"code": "Manual Review Required"}).status_code == 200
    assert _preview(run_id)["recommended_code_status"] == crs_export.CODE_DECIDED_BY_ENGINEER


def test_no_code_prints_no_status():
    assert _preview(_run(recommended=None))["recommended_code_status"] == ""

