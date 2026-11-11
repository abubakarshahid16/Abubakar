"""R21 (#785): each finding in the findings list carries its requirement's own
scope decision from the run's ledger - applies or not, the plain-words reason
and who decided - so the engineer sees why the requirement applies next to
the evidence.

What must hold: the decision is the ledger's own row for that run and
requirement (never invented: none recorded -> null); a standard the caller may
not read withholds it like the clause; the list stays read only. Synthetic
documents only.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import review_jobs, scope_ledger
from app.db import connect
from app.main import app
from tests.test_p3_review_jobs import W, _enqueue, _user, temp_storage, world  # noqa: F401 - fixtures


def _reviewed(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _findings(world, run_id, headers=None):
    r = TestClient(app).get("/api/reviews/findings", headers=headers or world["admin"],
                            params={"review_run_id": run_id})
    assert r.status_code == 200, r.text
    return r.json()["findings"]


def _standard_finding(findings, world):
    return next(f for f in findings if f.get("standard_document_id") == world["std"])


def test_a_finding_carries_its_requirements_own_ledger_row(world):
    run_id = _reviewed(world)
    finding = _standard_finding(_findings(world, run_id), world)
    rows = {d["requirement_id"]: d for d in scope_ledger.decisions_for(run_id)}
    assert finding["requirement_id"] in rows
    row = rows[finding["requirement_id"]]
    assert finding["scope_decision"] == {k: row[k] for k in ("state", "reason_code", "reason", "decided_by")}


def test_a_changed_ledger_row_is_what_the_finding_shows(world):
    run_id = _reviewed(world)
    finding = _standard_finding(_findings(world, run_id), world)
    with connect() as conn:
        conn.execute("UPDATE review_scope_decisions SET reason = ?, decided_by = ? "
                     "WHERE review_run_id = ? AND requirement_id = ?",
                     ("Applies: the sheet states a pump in this service", "engineer",
                      run_id, finding["requirement_id"]))
    again = _standard_finding(_findings(world, run_id), world)
    assert again["scope_decision"]["reason"] == "Applies: the sheet states a pump in this service"
    assert again["scope_decision"]["decided_by"] == "engineer"


def test_no_ledger_row_is_null_never_an_invented_reason(world):
    run_id = _reviewed(world)
    with connect() as conn:
        conn.execute("DELETE FROM review_scope_decisions WHERE review_run_id = ?", (run_id,))
    findings = _findings(world, run_id)
    assert findings and all(f["scope_decision"] is None for f in findings)
    with connect() as conn:
        conn.execute("DROP TABLE review_scope_decisions")      # a database from before the ledger
    assert all(f["scope_decision"] is None for f in _findings(world, run_id))


def test_a_standard_the_caller_may_not_read_withholds_it(world):
    run_id = _reviewed(world)
    sub_only = _user("subonly", [world["sub"]])
    findings = _findings(world, run_id, headers=sub_only)
    withheld = [f for f in findings if f.get("standard_withheld")]
    assert withheld and all(f["scope_decision"] is None for f in withheld)


def test_listing_writes_nothing(world):
    run_id = _reviewed(world)
    before = scope_ledger.decisions_for(run_id)
    _findings(world, run_id)
    assert scope_ledger.decisions_for(run_id) == before
