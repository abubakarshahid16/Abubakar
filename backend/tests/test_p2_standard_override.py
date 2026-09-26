"""P2: an engineer adds or removes a standard on a review, with a reason.

The capability (`applicability.override`) existed and was audited, but nothing
could call it: no route, no screen. These tests hold the route to the rules -
the engineer's own identity, both documents readable, a reason, an audit row
in the same transaction, the findings recomputed, a decided run left alone,
missing standards still missing, and no automatic selection replacing the
engineer's row. Synthetic documents only.
"""
from __future__ import annotations

import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app import (access, applicability, auth, comparison, datasheets, db, keyword,
                 standards, submittal_review)
from app.config import settings
from app.main import app

NOW = "2026-09-26T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "p2.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
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
                     "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'5.1 Noise',"
                     "'prose',?,1,?,1)", (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"))
    keyword.index_document(doc_id)
    return doc_id


def _user(user_id, docs):
    with db.connect() as conn:
        conn.execute("INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
                     " VALUES (?,?,?,'x',1,?)", (user_id, f"{user_id}@x", user_id, NOW))
        conn.execute("INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
                     " VALUES (?,?,'','discipline',?)", (f"r-{user_id}", f"r-{user_id}", NOW))
        conn.execute("INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
                     (user_id, f"r-{user_id}", NOW))
        for d in docs:
            conn.execute("INSERT INTO document_role_access (document_id,role_id,granted_at)"
                         " VALUES (?,?,?)", (d, f"r-{user_id}", NOW))
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


@pytest.fixture
def world():
    """A pump datasheet stating a noise level, a standard limiting it, and a
    completed run that did NOT select that standard."""
    std = _doc("std_noise", "COMPANY_STANDARD", "Equipment noise level shall not exceed 90 dB(A).")
    other = _doc("std_other", "COMPANY_STANDARD", "Spacing shall be at least 7.5 m.")
    sub = _doc("sub_pump", "CONTRACTOR_SUBMITTAL", "Noise level 95 dB(A)")
    ALL = frozenset({std, other, sub})
    standards.extract_requirements(std, allowed_document_ids=ALL)
    standards.extract_requirements(other, allowed_document_ids=ALL)
    datasheets.create_fact(submittal_document_id=sub, chunk_id=f"{sub}-c1",
                           field_label="Noise level", raw_value="95", unit="dB(A)", page=1)
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute("INSERT INTO review_runs (id,submittal_document_id,status,refusal_reason,"
                     "created_at,updated_at) VALUES (?,?,'completed',?,?,?)",
                     (run, sub, json.dumps({"recommended_code": "Manual Review Required",
                                             "missing_references": [{"identifier": "STD-MISSING-1",
                                                                     "status": "MISSING_LOCALLY"}]}), NOW, NOW))
    applicability.record_selection(review_run_id=run, standard_document_id=other,
                                   method=applicability.METHOD_DISCIPLINE, reason="discipline",
                                   included=True)
    engineer = _user("eng", [std, other, sub])
    return {"std": std, "other": other, "sub": sub, "run": run, "engineer": engineer}


def _override(w, headers, include=True, reason="the pump noise limit governs this sheet",
              standard=None):
    return TestClient(app).post(f"/api/reviews/runs/{w['run']}/standards/override", headers=headers,
                                json={"standard_document_id": standard or w["std"],
                                      "include": include, "reason": reason})


def _findings(run):
    return db.connect().execute(
        "SELECT compliance_status, standard_document_id FROM review_findings WHERE review_run_id = ?",
        (run,)).fetchall()


def test_an_engineer_adds_a_standard_and_the_findings_follow(world):
    before = [f for f in _findings(world["run"]) if f["standard_document_id"] == world["std"]]
    assert before == []
    r = _override(world, world["engineer"])
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["standards"] if s["standard_document_id"] == world["std"])
    assert row["included"] is True and row["selection_method"] == applicability.METHOD_MANUAL
    assert row["selection_reason"] == "the pump noise limit governs this sheet"
    added = [f for f in _findings(world["run"]) if f["standard_document_id"] == world["std"]]
    assert [f["compliance_status"] for f in added] == [comparison.NON_COMPLIANT]


def test_the_override_is_audited_with_the_engineer(world):
    _override(world, world["engineer"])
    rows = db.connect().execute(
        "SELECT * FROM audit_events WHERE action = 'review.applicability_override'").fetchall()
    assert len(rows) == 1 and rows[0]["actor_user_id"] == "eng"
    assert world["std"] in rows[0]["detail"] and "included=True" in rows[0]["detail"]


def test_an_engineer_removes_a_standard_with_a_reason(world):
    _override(world, world["engineer"])
    r = _override(world, world["engineer"], include=False, reason="the limit is for fixed equipment")
    assert r.status_code == 200, r.text
    row = next(s for s in r.json()["standards"] if s["standard_document_id"] == world["std"])
    assert row["included"] is False and row["exclusion_reason"] == "the limit is for fixed equipment"
    assert [f for f in _findings(world["run"]) if f["standard_document_id"] == world["std"]] == []


def test_missing_standards_stay_missing_and_the_run_is_not_approved(world):
    r = _override(world, world["engineer"])
    assert [m["identifier"] for m in r.json()["missing_references"]] == ["STD-MISSING-1"]
    out = json.loads(db.connect().execute("SELECT refusal_reason FROM review_runs WHERE id = ?",
                                          (world["run"],)).fetchone()[0])
    assert out["recommended_code"] not in (comparison.CODE_APPROVED, comparison.CODE_APPROVED_WITH_COMMENTS)


def test_a_user_who_cannot_read_the_standard_cannot_change_the_run(world):
    stranger = _user("stranger", [world["sub"], world["other"]])
    assert _override(world, stranger).status_code == 404
    assert db.connect().execute("SELECT COUNT(*) FROM audit_events WHERE action = "
                                "'review.applicability_override'").fetchone()[0] == 0


def test_an_anonymous_caller_is_refused(world):
    assert _override(world, {}).status_code == 401


def test_a_reason_is_required(world):
    assert _override(world, world["engineer"], reason="").status_code == 422


def test_a_decided_run_is_not_changed_underneath_its_code(world):
    with db.connect() as conn:
        conn.execute("UPDATE review_runs SET engineer_final_code = 'Manual Review Required'"
                     " WHERE id = ?", (world["run"],))
    assert _override(world, world["engineer"]).status_code == 409


def test_an_automatic_selection_never_replaces_the_engineers_row(world):
    _override(world, world["engineer"], include=False, reason="not for this equipment")
    applicability.record_selection(review_run_id=world["run"], standard_document_id=world["std"],
                                   method=applicability.METHOD_REFERENCED, reason="cited", included=True)
    row = db.connect().execute("SELECT * FROM review_applicable_standards WHERE review_run_id = ?"
                               " AND standard_document_id = ?", (world["run"], world["std"])).fetchone()
    assert row["selection_method"] == applicability.METHOD_MANUAL and row["included"] == 0


def test_a_caller_who_cannot_see_every_standard_in_use_cannot_recompute(world):
    """Recomputing under a narrower view would silently drop requirements."""
    partial = _user("partial", [world["std"], world["sub"]])     # not std_other
    r = _override(world, partial)
    assert r.status_code == 409 and "every standard" in r.text


def test_without_sign_in_no_engineer_can_be_named(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    assert _override(world, {}).status_code == 401
