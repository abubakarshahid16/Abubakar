"""Order 109: the runs list reads each run's stored outcome and AI-check
status from the run row it already holds, under the caller's grants, instead
of re-reading every run by id (three scoped reads per row, each `IN` every
readable document). Same values, fewer reads.

Invented runs only.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import access, db, submittal_review
from app.main import app
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _run,
    _submittal,
    temp_db,
)


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def test_the_list_carries_each_runs_stored_outcome_and_ai_check_status():
    doc = _submittal()
    run = _run(doc, recommended="Approved with Comments")
    status = {"state": "done", "plain": "The AI check read 3 findings."}
    with db.connect() as conn:
        conn.execute(
            "UPDATE review_runs SET ai_check_status = ? WHERE id = ?",
            (json.dumps(status), run),
        )
    [row] = _client(doc).get("/api/reviews/runs").json()["runs"]
    assert row["recommended_code"] == "Approved with Comments"
    assert row["ai_check_status"] == status
    detail = _client(doc).get(f"/api/reviews/runs/{run}/ai-numbers")
    assert detail.status_code == 200, detail.text


def test_the_list_does_not_re_read_each_run_by_id(monkeypatch):
    doc = _submittal()
    for _ in range(5):
        _run(doc)
    calls: list[str] = []
    real = submittal_review.get_review_run

    def counted(run_id, **kw):
        calls.append(run_id)
        return real(run_id, **kw)

    monkeypatch.setattr(submittal_review, "get_review_run", counted)
    rows = _client(doc).get("/api/reviews/runs").json()["runs"]
    assert len(rows) == 5
    assert calls == []


def test_run_outcome_is_the_scoped_read_plus_the_one_parser():
    from app import comparison

    doc = _submittal()
    run = _run(doc, recommended="Approved with Comments")
    outcome = comparison.run_outcome(run, allowed_document_ids=frozenset({doc}))
    assert outcome["recommended_code"] == "Approved with Comments"
    assert (
        comparison.run_outcome(run, allowed_document_ids=frozenset({"elsewhere"}))
        is None
    )
