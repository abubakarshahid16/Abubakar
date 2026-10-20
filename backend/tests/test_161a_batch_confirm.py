"""Order 161 item A: an engineer confirms the values of one page at once, and the
run is judged again so the findings that rested on them state a verdict.

Held before, judged after: a model-read value nobody has confirmed holds its
finding as LOW_TRUST_VALUE; after the batch confirmation the same comparison
(the run's own, not a second one) states the verdict. All or none; unsigned is
refused; a decided run is left alone. Invented documents and values only.
"""

from __future__ import annotations

import json
import secrets
import uuid

import pytest
from fastapi.testclient import TestClient

from app import (
    access,
    applicability,
    auth,
    comparison,
    datasheets,
    db,
    fts_index,
    standards,
    submittal_review,
)
from app.config import settings
from app.main import app

NOW = "2026-10-20T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "b161.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_REQUIRED)
    monkeypatch.setattr(settings, "auth_secret", secrets.token_urlsafe(48))
    monkeypatch.setattr(settings, "geometry_reader_enabled", False)
    db.reset_connection()
    db.init_db()
    submittal_review.ensure_schema()
    submittal_review.migrate_facts_to_per_document()
    fts_index.ensure_schema()
    access.set_user_resolver(auth.resolve_user_id)
    yield
    access.set_user_resolver(None)
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()


def _doc(doc_id, role, text):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES (?,?,?,1,'/x','ready',1,?)",
            (doc_id, f"{doc_id}.pdf", f"sha-{doc_id}", NOW),
        )
        conn.execute(
            "INSERT INTO document_classification (document_id,suggested_by,document_role)"
            " VALUES (?,?,?)",
            (doc_id, "test", role),
        )
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,"
            "kind,text,token_count,content_hash,retrievable) VALUES (?,?,?,0,1,1,'5.1 Noise',"
            "'prose',?,1,?,1)",
            (f"{doc_id}-c1", doc_id, f"{doc_id}.pdf", text, f"h-{doc_id}"),
        )
    fts_index.index_document(doc_id)
    return doc_id


def _user(user_id, docs):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO users (id,email,display_name,password_hash,is_active,created_at)"
            " VALUES (?,?,?,'x',1,?)",
            (user_id, f"{user_id}@x", user_id, NOW),
        )
        conn.execute(
            "INSERT OR IGNORE INTO roles (id,name,description,kind,created_at)"
            " VALUES (?,?,'','discipline',?)",
            (f"r-{user_id}", f"r-{user_id}", NOW),
        )
        conn.execute(
            "INSERT INTO user_roles (user_id,role_id,granted_at) VALUES (?,?,?)",
            (user_id, f"r-{user_id}", NOW),
        )
        for d in docs:
            conn.execute(
                "INSERT INTO document_role_access (document_id,role_id,granted_at)"
                " VALUES (?,?,?)",
                (d, f"r-{user_id}", NOW),
            )
    return {"Authorization": f"Bearer {auth.issue_token(user_id)}"}


def _model_fact(sub, label, value, unit):
    """A value only a model read: no proved quote, so it is not trusted yet."""
    return datasheets.create_fact(
        submittal_document_id=sub,
        chunk_id=f"{sub}-c1",
        field_label=label,
        raw_value=value,
        unit=unit,
        page=1,
        confidence=0.5,
        extraction_method="model",
    )["id"]


@pytest.fixture
def world():
    std = _doc(
        "std_noise",
        "COMPANY_STANDARD",
        "Equipment noise level shall not exceed 90 dB(A).",
    )
    sub = _doc("sub_pump", "CONTRACTOR_SUBMITTAL", "Noise level 95 dB(A)")
    other = _doc("sub_other", "CONTRACTOR_SUBMITTAL", "Noise level 70 dB(A)")
    ALL = frozenset({std, sub, other})
    standards.extract_requirements(std, allowed_document_ids=ALL)
    fact = _model_fact(sub, "Noise level", "95", "dB(A)")
    foreign = _model_fact(other, "Noise level", "70", "dB(A)")
    run = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,"
            "created_at,updated_at) VALUES (?,?,'completed',?,?,?)",
            (
                run,
                sub,
                json.dumps({"recommended_code": "Manual Review Required"}),
                NOW,
                NOW,
            ),
        )
    applicability.record_selection(
        review_run_id=run,
        standard_document_id=std,
        method=applicability.METHOD_DISCIPLINE,
        reason="discipline",
        included=True,
    )
    comparison.run_comparison(run, allowed_document_ids=ALL)
    return {
        "std": std,
        "sub": sub,
        "run": run,
        "fact": fact,
        "foreign": foreign,
        "engineer": _user("eng", [std, sub]),
    }


def _statuses(run):
    """The noise-limit finding's status (the run also holds an unrelated
    mandatory-field finding that a confirmation must not move)."""
    return [
        r["compliance_status"]
        for r in db.connect().execute(
            "SELECT compliance_status FROM review_findings WHERE review_run_id = ?"
            " AND requirement LIKE '%noise level%'",
            (run,),
        )
    ]


def _confirm(w, ids, headers=None):
    return TestClient(app).post(
        f"/api/reviews/runs/{w['run']}/facts/confirm",
        headers=w["engineer"] if headers is None else headers,
        json={"fact_ids": ids},
    )


def _confirmed_by(fact_id):
    return (
        db.connect()
        .execute("SELECT confirmed_by FROM submittal_facts WHERE id = ?", (fact_id,))
        .fetchone()[0]
    )


def test_the_fixture_holds_the_finding_until_the_value_is_confirmed(world):
    assert _statuses(world["run"]) == [comparison.NEEDS_ENGINEER_REVIEW]
    assert _confirmed_by(world["fact"]) is None


def test_a_batch_confirmation_judges_the_run_again_and_the_verdict_appears(world):
    r = _confirm(world, [world["fact"]])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["confirmed"] == 1 and body["already_confirmed"] == 0
    assert body["held_before"] == 1 and body["held_after"] == 0
    assert body["status_before"].get(comparison.NON_COMPLIANT) is None
    assert body["status_after"][comparison.NON_COMPLIANT] == 1
    # the unrelated mandatory-field finding is still there, unmoved
    assert (
        body["status_after"][comparison.NEEDS_ENGINEER_REVIEW]
        == body["status_before"][comparison.NEEDS_ENGINEER_REVIEW] - 1
    )
    assert "this review run" in body["boundary"]
    assert _statuses(world["run"]) == [comparison.NON_COMPLIANT]
    assert _confirmed_by(world["fact"]) == "eng"
    trail = (
        db.connect()
        .execute(
            "SELECT actor_user_id, detail FROM audit_events WHERE action = 'fact.confirmed'"
            " AND resource_id = ?",
            (world["fact"],),
        )
        .fetchall()
    )
    assert [tuple(t) for t in trail] == [("eng", "document=sub_pump")]
    assert "95" not in (trail[0]["detail"] or "")


def test_a_value_already_confirmed_keeps_its_first_name(world):
    assert _confirm(world, [world["fact"]]).status_code == 200
    again = _confirm(world, [world["fact"]])
    assert again.status_code == 200
    assert again.json()["confirmed"] == 0 and again.json()["already_confirmed"] == 1
    assert (
        db.connect()
        .execute("SELECT COUNT(*) FROM audit_events WHERE action = 'fact.confirmed'")
        .fetchone()[0]
        == 1
    )


def test_all_or_none_one_foreign_value_refuses_the_whole_batch(world):
    r = _confirm(world, [world["fact"], world["foreign"]])
    assert r.status_code == 404, r.text
    assert (
        _confirmed_by(world["fact"]) is None and _confirmed_by(world["foreign"]) is None
    )
    assert _statuses(world["run"]) == [comparison.NEEDS_ENGINEER_REVIEW]
    assert _confirm(world, [world["fact"], "no-such-fact"]).status_code == 404
    assert _confirmed_by(world["fact"]) is None


def test_a_value_re_read_since_refuses_the_whole_batch(world):
    with db.connect() as conn:
        conn.execute(
            "UPDATE submittal_facts SET superseded_at = ? WHERE id = ?",
            (NOW, world["fact"]),
        )
    r = _confirm(world, [world["fact"]])
    assert r.status_code == 409, r.text
    assert _confirmed_by(world["fact"]) is None


def test_nobody_confirms_a_batch_unsigned(world, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    r = _confirm(world, [world["fact"]], headers={})
    assert r.status_code == 401, r.text
    assert _confirmed_by(world["fact"]) is None


def test_a_run_with_an_engineers_final_code_is_left_alone(world):
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET engineer_final_code = 'A' WHERE id = ?",
            (world["run"],),
        )
    r = _confirm(world, [world["fact"]])
    assert r.status_code == 409, r.text
    assert _confirmed_by(world["fact"]) is None


def test_an_empty_or_unknown_request_is_refused(world):
    assert _confirm(world, []).status_code == 422
    r = TestClient(app).post(
        f"/api/reviews/runs/{world['run']}/facts/confirm",
        headers=world["engineer"],
        json={"fact_ids": ["x"], "extra": 1},
    )
    assert r.status_code == 422
    hidden = _user("stranger", [])
    assert _confirm(world, [world["fact"]], headers=hidden).status_code == 404
