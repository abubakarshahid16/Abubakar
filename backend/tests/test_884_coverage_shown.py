"""PF4 step 2 (#884): the run's clause coverage is SHOWN - on the CRS Review
notes (internal copy) and on the run the Sheet reads - from the record the
run stored at its end (PR #1013), the same line in every home (rule 8). A run
with no record says so; it is never 0. Invented runs only.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app import access, clause_coverage as cov, comparison, crs_mapping
from app.main import app
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture
from tests.test_w5_677_scope_ledger import review_run  # noqa: F401 - fixture


def test_the_review_note_says_the_stored_line_or_that_none_is_recorded():
    stored = {"applicable": 9, "counts": {}, "checked_share": 44.4, "adds_up": True,
              "line": "4 of 9 applicable requirement(s) checked (44.4%), 2 sent to the engineer, 2 not checked"}
    [note] = cov.review_notes({"clause_coverage": stored})
    assert note["note"] == "Clause coverage" and note["count"] == 9
    assert note["detail"].startswith(stored["line"] + ". The share is out of this run's applicable")
    assert "not as proof the whole standard was checked" in note["detail"]
    [old] = cov.review_notes({})
    assert old["count"] is None and "not recorded for this run" in old["detail"]
    assert cov.review_notes(None) == cov.review_notes({})


def test_the_crs_review_notes_carry_the_runs_own_coverage(review_run):
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    outcome = comparison.run_outcome(run, allowed_document_ids=scope)
    notes = crs_mapping.build_review_notes([], [], [], outcome)
    [note] = [n for n in notes if n["note"] == "Clause coverage"]
    assert note["count"] == outcome["clause_coverage"]["applicable"] == 2
    assert note["detail"].startswith(outcome["clause_coverage"]["line"])
    # a run with no stored record (made before PF4 step 1) says so
    [old] = [n for n in crs_mapping.build_review_notes([], [], [], {}) if n["note"] == "Clause coverage"]
    assert "not recorded" in old["detail"] and old["count"] is None


def test_the_run_the_sheet_reads_carries_the_same_record(review_run):
    run, _ids, scope = review_run
    comparison.run_comparison(run, allowed_document_ids=scope)
    stored = comparison.run_outcome(run, allowed_document_ids=scope)["clause_coverage"]
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="adm", allowed_document_ids=scope)
    try:
        body = TestClient(app).get("/api/reviews/runs").json()
    finally:
        app.dependency_overrides.pop(access.current_scope, None)
    [row] = [r for r in body["runs"] if r["review_run_id"] == run]
    assert row["clause_coverage"] == stored and stored["line"].startswith("1 of 2 applicable")
