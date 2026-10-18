"""Order 109: `GET /api/reviews/runs/{id}` - one run, the same shape and the
same values as that run's row in `GET /api/reviews/runs` (one definition,
`main._run_summary`), so a screen showing one run stops fetching every run.

Invented runs and findings only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access
from app.main import app
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _finding,
    _run,
    _submittal,
    temp_db,
)


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def test_one_run_is_exactly_its_row_in_the_list():
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    run = _run(doc)
    _run(other)
    _finding(doc, run, "NON_COMPLIANT")
    _finding(doc, run, "COMPLIANT")
    client = _client(doc, other)
    rows = client.get("/api/reviews/runs").json()["runs"]
    [row] = [r for r in rows if r["review_run_id"] == run]
    detail = client.get(f"/api/reviews/runs/{run}")
    assert detail.status_code == 200, detail.text
    assert detail.json() == row
    assert detail.json()["findings_total"] == 2


def test_a_run_the_caller_may_not_read_is_404_like_a_missing_one():
    doc = _submittal()
    run = _run(doc)
    stranger = _client("doc_other")
    assert stranger.get(f"/api/reviews/runs/{run}").status_code == 404
    assert _client(doc).get("/api/reviews/runs/no-such-run").status_code == 404


def test_an_unknown_parameter_is_refused():
    doc = _submittal()
    run = _run(doc)
    assert _client(doc).get(f"/api/reviews/runs/{run}?full=1").status_code == 422
