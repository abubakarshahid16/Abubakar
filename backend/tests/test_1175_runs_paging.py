"""Order 117 item 5: `GET /api/reviews/runs` can return one page.

`limit`/`offset` are optional; without them the list is every run, as before.
`total` is always every run the caller may read under the same filter, so a
page states its population (CLAUDE.md rule 4). Only the page is summarised.

Invented runs only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access
from app import main as main_mod
from app.main import app
from tests.test_crs_endpoint import _run, _submittal, temp_db  # noqa: F401 - fixture


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def _ids(body: dict) -> list[str]:
    return [r["review_run_id"] for r in body["runs"]]


def test_without_a_page_every_run_comes_back_with_its_total():
    doc = _submittal()
    runs = {_run(doc) for _ in range(3)}
    body = _client(doc).get("/api/reviews/runs").json()
    assert set(_ids(body)) == runs
    assert body["total"] == 3
    assert body["limit"] is None and body["offset"] == 0


def test_pages_cover_every_run_once_in_list_order_and_keep_the_total():
    doc = _submittal()
    for _ in range(5):
        _run(doc)
    client = _client(doc)
    whole = _ids(client.get("/api/reviews/runs").json())
    pages = [
        client.get(f"/api/reviews/runs?limit=2&offset={o}").json() for o in (0, 2, 4)
    ]
    assert [len(p["runs"]) for p in pages] == [2, 2, 1]
    assert [i for p in pages for i in _ids(p)] == whole
    assert {p["total"] for p in pages} == {5}
    past_the_end = client.get("/api/reviews/runs?limit=2&offset=9").json()
    assert past_the_end["runs"] == [] and past_the_end["total"] == 5


def test_the_total_counts_only_what_the_caller_may_read_under_the_filter():
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    _run(doc)
    _run(doc)
    _run(other)
    assert _client(doc).get("/api/reviews/runs?limit=1").json()["total"] == 2
    both = _client(doc, other)
    assert both.get("/api/reviews/runs?limit=1").json()["total"] == 3
    narrowed = both.get(f"/api/reviews/runs?document_id={other}&limit=1").json()
    assert narrowed["total"] == 1


def test_only_the_asked_for_page_is_summarised(monkeypatch):
    doc = _submittal()
    for _ in range(4):
        _run(doc)
    calls = []
    real = main_mod._run_summary
    monkeypatch.setattr(
        main_mod,
        "_run_summary",
        lambda run, scope: calls.append(run) or real(run, scope),
    )
    body = _client(doc).get("/api/reviews/runs?limit=1&offset=1").json()
    assert len(calls) == 1 and body["total"] == 4


def test_a_bad_page_is_refused():
    doc = _submittal()
    client = _client(doc)
    for query in ("limit=0", "limit=201", "offset=-1", "page=2"):
        assert client.get(f"/api/reviews/runs?{query}").status_code == 422, query
