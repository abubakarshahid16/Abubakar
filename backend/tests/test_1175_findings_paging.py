"""Order 117 item 5: `GET /api/reviews/findings` can return one page.

`limit`/`offset` are optional; without them every finding comes back, as
before. `total` counts every finding under the same filter and scope, so a
page states its population (CLAUDE.md rule 4). The page is cut in the query,
after the scope filter, in a fixed order.

Invented findings only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access
from app.main import app
from tests.test_crs_endpoint import _finding, _run, _submittal, temp_db  # noqa: F401


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def _ids(body: dict) -> list[str]:
    return [f["id"] for f in body["findings"]]


def test_without_a_page_every_finding_comes_back_with_its_total():
    doc = _submittal()
    run = _run(doc)
    for _ in range(3):
        _finding(doc, run, "COMPLIANT")
    body = _client(doc).get("/api/reviews/findings").json()
    assert len(body["findings"]) == 3 and body["total"] == 3
    assert body["limit"] is None and body["offset"] == 0


def test_pages_cover_every_finding_once_in_list_order():
    doc = _submittal()
    run = _run(doc)
    # one severity and one second: only the id tiebreak fixes the order
    for _ in range(7):
        _finding(doc, run, "NON_COMPLIANT")
    _finding(doc, run, "NON_COMPLIANT", severity="critical")
    client = _client(doc)
    whole = _ids(client.get("/api/reviews/findings").json())
    pages = [
        client.get(f"/api/reviews/findings?limit=3&offset={o}").json()
        for o in (0, 3, 6)
    ]
    assert [i for p in pages for i in _ids(p)] == whole
    assert pages[0]["findings"][0]["severity"] == "critical"
    assert {p["total"] for p in pages} == {8}


def test_the_total_counts_only_findings_the_caller_may_read_under_the_filter():
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    run, other_run = _run(doc), _run(other)
    _finding(doc, run, "COMPLIANT")
    _finding(doc, run, "NON_COMPLIANT")
    _finding(other, other_run, "COMPLIANT")
    assert _client(doc).get("/api/reviews/findings?limit=1").json()["total"] == 2
    both = _client(doc, other)
    assert both.get("/api/reviews/findings?limit=1").json()["total"] == 3
    assert (
        both.get(f"/api/reviews/findings?review_run_id={other_run}&limit=1").json()[
            "total"
        ]
        == 1
    )
    assert (
        both.get(f"/api/reviews/findings?document_id={doc}&limit=1").json()["total"]
        == 2
    )
    # a run the caller may not read stays empty, page or no page
    stranger = _client(doc).get(
        f"/api/reviews/findings?review_run_id={other_run}&limit=5"
    )
    assert stranger.json()["findings"] == [] and stranger.json()["total"] == 0
    assert _client().get("/api/reviews/findings?limit=5").json()["total"] == 0


def test_a_bad_page_is_refused():
    client = _client(_submittal())
    for query in ("limit=0", "limit=1001", "offset=-1", "page=2"):
        assert client.get(f"/api/reviews/findings?{query}").status_code == 422, query
