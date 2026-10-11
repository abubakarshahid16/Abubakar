"""R26 step 10 (#763, R4 #768): engineers' accept / edit / reject decisions
become a measured precision per standard and per rule.

What must hold: each decision is counted once, as what the engineer did
(a rejection wins over an earlier confirmation; an edit is kept in their
words); undecided findings are pending, never right or wrong; precision is
"kept of decided", never a percentage; only the caller's documents are
counted and a standard they may not read is never named; a rule engineers
keep rejecting is listed as a candidate and nothing changes by itself; the
route is read only. Synthetic documents only.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import engineer_feedback, review_jobs
from app.db import connect
from app.main import app
from tests.test_p3_review_jobs import W, _enqueue, _user, temp_storage, world  # noqa: F401 - fixtures


def _reviewed(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _findings(run_id):
    return [dict(r) for r in connect().execute(
        "SELECT * FROM review_findings WHERE review_run_id = ? ORDER BY id", (run_id,))]


def _decide(world, finding_id, **body):
    r = TestClient(app).patch(f"/api/reviews/findings/{finding_id}", headers=world["admin"], json=body)
    assert r.status_code == 200, r.text


def _report(world, headers=None, **params):
    r = TestClient(app).get("/api/reviews/feedback", headers=headers or world["admin"], params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_each_decision_is_counted_as_what_the_engineer_did(world):
    run_id = _reviewed(world)
    rows = _findings(run_id)
    assert len(rows) >= 3
    _decide(world, rows[0]["id"], confirmed=True)
    _decide(world, rows[1]["id"], engineer_comment="Contractor to restate the value with its unit.")
    _decide(world, rows[2]["id"], confirmed=True)
    _decide(world, rows[2]["id"], approval_status="rejected")     # rejection wins
    body = _report(world)
    totals = body["totals"]
    assert (totals["accepted"], totals["edited"], totals["rejected"]) == (1, 1, 1)
    assert totals["pending"] == len(rows) - 3
    assert totals["precision"] == "2 of 3 kept"
    assert f"{len(rows)} review finding(s)" in body["boundary"] and "3 decided" in body["boundary"]
    assert "%" not in str(body)


def test_precision_is_split_by_standard_and_by_rule(world):
    run_id = _reviewed(world)
    rows = _findings(run_id)
    standard = next(r for r in rows if r["standard_document_id"] == world["std"])
    check = next(r for r in rows if r["origin"] == "datasheet_check")
    _decide(world, standard["id"], confirmed=True)
    _decide(world, check["id"], approval_status="rejected")
    body = _report(world)
    by_standard = {r["name"]: r for r in body["by_standard"]}
    assert by_standard["std_api.pdf"]["accepted"] == 1
    assert by_standard["Datasheet checklist"]["rejected"] == 1
    rules = {r["name"] for r in body["by_rule"]}
    assert any(name.startswith("std_api.pdf cl. ") for name in rules)
    assert "Datasheet checklist DS-M1" in rules


def test_a_rule_engineers_keep_rejecting_is_a_candidate_and_nothing_changes(world):
    run_id = _reviewed(world)
    checks = [r for r in _findings(run_id) if r["origin"] == "datasheet_check"]
    assert len(checks) >= 2
    for row in checks[:2]:
        _decide(world, row["id"], approval_status="rejected")
    before = _findings(run_id)
    body = _report(world)
    names = [c["name"] for c in body["candidates"]]
    assert "Datasheet checklist DS-M1" in names
    note = body["candidates"][names.index("Datasheet checklist DS-M1")]["note"]
    assert "Nothing changes automatically" in note
    assert _findings(run_id) == before     # read only


def test_only_the_callers_documents_are_counted_and_a_hidden_standard_is_not_named(world):
    run_id = _reviewed(world)
    rows = _findings(run_id)
    standard = next(r for r in rows if r["standard_document_id"] == world["std"])
    _decide(world, standard["id"], confirmed=True)
    stranger = _user("stranger", [])
    assert _report(world, stranger)["totals"]["decided"] == 0
    sub_only = _user("subonly", [world["sub"]])
    body = _report(world, sub_only)
    names = {r["name"] for r in body["by_standard"]} | {r["name"] for r in body["by_rule"]}
    assert "std_api.pdf" not in str(names)
    assert "A standard outside your access" in names


def test_undecided_findings_are_pending_not_right_or_wrong():
    finding = {"approval_status": "pending", "disposition": None, "engineer_comment": None,
               "confirmed_by": None}
    assert engineer_feedback.decision(finding) == engineer_feedback.PENDING
    assert engineer_feedback.decision({**finding, "disposition": "not_applicable"}) == "rejected"
    assert engineer_feedback.decision({**finding, "disposition": "partially_accepted"}) == "accepted"


def test_since_narrows_and_unknown_parameters_are_refused(world):
    run_id = _reviewed(world)
    _decide(world, _findings(run_id)[0]["id"], confirmed=True)
    assert _report(world, since="2999-01-01")["totals"]["decided"] == 0
    assert "since 2999-01-01" in _report(world, since="2999-01-01")["boundary"]
    r = TestClient(app).get("/api/reviews/feedback", headers=world["admin"], params={"user": "x"})
    assert r.status_code == 422
