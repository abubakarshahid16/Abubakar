"""Order 117 item 5: `GET /api/reviews/runs/counts` gives the tier counts of
many runs in one call, so the review inbox no longer asks `/summary` once per
row. Each run's counts are `/summary`'s own (one helper computes both). A run
that is not there, or that the caller may not read, is absent - never a 404
for the batch and never zeros (CLAUDE.md rule 5).

Invented runs and findings only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access
from app.api import run_summary
from app.main import app
from tests.test_crs_endpoint import _finding, _run, _submittal, temp_db  # noqa: F401

URL = "/api/reviews/runs/counts"


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def _query(*ids: str) -> str:
    return URL + "?" + "&".join(f"ids={i}" for i in ids)


def _two_runs(doc: str) -> tuple[str, str]:
    first = _run(doc)
    for status in ("COMPLIANT", "NON_COMPLIANT", "NEEDS_ENGINEER_REVIEW"):
        _finding(doc, first, status)
    second = _run(doc)
    _finding(doc, second, "COMPLIANT")
    _finding(doc, second, "MISSING_INFORMATION", approval_status="rejected")
    return first, second


def test_each_runs_counts_are_its_summarys_counts():
    doc = _submittal()
    first, second = _two_runs(doc)
    client = _client(doc)
    resp = client.get(_query(first, second, first))
    assert resp.status_code == 200
    body = resp.json()
    assert body["boundary"] == run_summary.BOUNDARY
    assert set(body["counts"]) == {first, second}
    for run_id in (first, second):
        summary = client.get(f"/api/reviews/runs/{run_id}/summary").json()
        assert body["counts"][run_id] == summary["counts"]
    assert body["counts"][first]["total"] == 3
    assert body["counts"][second]["total"] == 2


def test_a_run_the_caller_may_not_read_is_absent_not_zero():
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    mine = _run(doc)
    _finding(doc, mine, "COMPLIANT")
    hidden = _run(other)
    _finding(other, hidden, "COMPLIANT")
    body = _client(doc).get(_query(mine, hidden)).json()
    assert set(body["counts"]) == {mine}
    both = _client(doc, other).get(_query(mine, hidden)).json()
    assert set(both["counts"]) == {mine, hidden}


def test_an_unknown_run_is_absent_and_the_batch_is_not_a_404():
    doc = _submittal()
    known = _run(doc)
    resp = _client(doc).get(_query(known, "no-such-run"))
    assert resp.status_code == 200
    assert set(resp.json()["counts"]) == {known}
    only_unknown = _client(doc).get(_query("no-such-run"))
    assert only_unknown.status_code == 200
    assert only_unknown.json()["counts"] == {}


def test_no_ids_too_many_ids_or_an_unknown_param_is_refused():
    doc = _submittal()
    client = _client(doc)
    assert client.get(URL).status_code == 422
    too_many = [f"r{i}" for i in range(run_summary.RUN_COUNTS_MAX_IDS + 1)]
    assert client.get(_query(*too_many)).status_code == 422
    assert client.get(_query("a") + "&page=2").status_code == 422
    at_the_cap = [f"r{i}" for i in range(run_summary.RUN_COUNTS_MAX_IDS)]
    assert client.get(_query(*at_the_cap)).status_code == 200


def test_counts_is_not_read_as_a_run_id():
    doc = _submittal()
    run_id = _run(doc)
    body = _client(doc).get(_query(run_id)).json()
    assert set(body) == {"boundary", "counts"}
    assert "review_run_id" not in body
