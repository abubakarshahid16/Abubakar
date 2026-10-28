"""#962: the generic route that sets a finding of a run to "rejected" keeps a reason of record,
as the issue gate's Reject does. Invented findings only."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access, crs_issue, db, review, submittal_review
from app.config import settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"
RUN = "run-962"
BASE = {
    "document_id": "d1",
    "category": "requirement_deviation",
    "severity": "major",
    "requirement": "The noise level shall not exceed a stated limit.",
    "finding": "A higher value was submitted.",
    "required_action": "Revise.",
}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t962.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,"
            "uploaded_at) VALUES ('d1','d1.pdf','s1',1,'/x','ready',1,?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,created_at)"
            " VALUES ('eng-1','e@x','Eng','h',?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO roles (id,name,description,kind,created_at)"
            " VALUES ('r1','r1','r','discipline',?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES ('eng-1','r1',?)",
            (NOW,),
        )
        conn.execute(
            "INSERT INTO document_role_access (document_id,role_id,granted_at)"
            " VALUES ('d1','r1',?)",
            (NOW,),
        )
    access.set_user_resolver(lambda request: "eng-1")
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _finding(in_run: bool = True) -> str:
    client = TestClient(app)
    fid = client.post("/api/reviews/findings", json=BASE).json()["id"]
    if in_run:
        with db.connect() as conn:
            conn.execute(
                "UPDATE review_findings SET review_run_id = ? WHERE id = ?", (RUN, fid)
            )
    return fid


def _patch(fid, **body):
    return TestClient(app).patch(f"/api/reviews/findings/{fid}", json=body)


def _status(fid):
    return review.get(fid)["approval_status"]


def test_a_rejection_of_a_finding_of_a_run_without_a_reason_is_refused():
    fid = _finding()
    r = _patch(fid, approval_status="rejected")
    assert r.status_code == 422, r.text
    assert _status(fid) == "pending"
    assert crs_issue.decisions(RUN) == []


def test_a_reason_too_short_is_refused_like_the_gate_refuses_it():
    fid = _finding()
    assert _patch(fid, approval_status="rejected", reason="no").status_code == 422
    assert _status(fid) == "pending"


def test_a_rejection_with_a_reason_is_kept_in_the_gate_record():
    fid = _finding()
    r = _patch(
        fid,
        approval_status="rejected",
        reason="the clause is for another kind of valve",
    )
    assert r.status_code == 200, r.text
    assert _status(fid) == "rejected"
    [record] = crs_issue.decisions(RUN)
    assert record["subject"] == fid and record["decision"] == crs_issue.REJECT
    assert record["reason"] == "the clause is for another kind of valve"
    assert record["decided_by"] == "eng-1"


def test_a_listed_reason_code_is_a_reason():
    fid = _finding()
    r = _patch(fid, approval_status="rejected", reason_code="not_applicable")
    assert r.status_code == 200, r.text
    [record] = crs_issue.decisions(RUN)
    assert record["reason"] == crs_issue.REMOVAL_REASONS["not_applicable"]


def test_an_unlisted_reason_code_is_refused():
    fid = _finding()
    assert (
        _patch(fid, approval_status="rejected", reason_code="because").status_code
        == 422
    )
    assert _status(fid) == "pending"


def test_saving_an_already_rejected_finding_needs_no_second_reason():
    fid = _finding()
    assert (
        _patch(fid, approval_status="rejected", reason_code="duplicate").status_code
        == 200
    )
    assert (
        _patch(fid, approval_status="rejected", response_text="noted").status_code
        == 200
    )
    assert len(crs_issue.decisions(RUN)) == 1


def test_a_finding_outside_any_run_is_rejected_as_before():
    fid = _finding(in_run=False)
    assert _patch(fid, approval_status="rejected").status_code == 200
    assert _status(fid) == "rejected"


def test_other_changes_to_a_finding_of_a_run_need_no_reason():
    fid = _finding()
    assert _patch(fid, approval_status="accepted").status_code == 200
    assert crs_issue.decisions(RUN) == []
