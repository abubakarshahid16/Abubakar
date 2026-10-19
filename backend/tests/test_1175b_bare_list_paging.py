"""Order 117 item 5, part 2: routes that answer with a bare JSON list take an
optional page and always state their total in `X-Total-Count`.

A body field cannot be added to a bare list without breaking its readers, so
the list stays a list; without `limit`/`offset` it is the whole list, as
before. Invented standards only.
"""

from __future__ import annotations

import pytest
from fastapi import Response
from fastapi.testclient import TestClient

from app import access, paging
from app.main import app
from tests.test_standards_library import (  # noqa: F401
    _chunk,
    _doc,
    _standard,
    temp_storage,
)


@pytest.fixture(autouse=True)
def _no_scope_left_behind():
    """`temp_storage` does not clear the scope override this file sets."""
    yield
    app.dependency_overrides.pop(access.current_scope, None)


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def test_page_of_cuts_the_list_and_states_the_whole_count():
    response = Response()
    assert paging.page_of(list(range(7)), 3, 3, response) == [3, 4, 5]
    assert response.headers[paging.TOTAL_HEADER] == "7"
    assert paging.page_of(list(range(7)), None, 5, Response()) == [5, 6]
    assert paging.page_of([], 3, 0, Response()) == []


def test_the_library_list_pages_and_counts_only_what_the_caller_may_read():
    docs = [_standard(_doc(f"doc_std{i}", f"STD-{i}.pdf")) for i in range(5)]
    hidden = _standard(_doc("doc_hidden", "HIDDEN.pdf"))
    client = _client(*docs)
    whole = client.get("/api/standards")
    assert whole.status_code == 200, whole.text
    assert whole.headers[paging.TOTAL_HEADER] == "5"
    ids = [s["id"] for s in whole.json()]
    assert hidden not in ids
    pages = [client.get(f"/api/standards?limit=2&offset={o}") for o in (0, 2, 4)]
    assert [s["id"] for p in pages for s in p.json()] == ids
    assert {p.headers[paging.TOTAL_HEADER] for p in pages} == {"5"}
    inventory = client.get("/api/standards/inventory?limit=1")
    assert len(inventory.json()) == 1 and inventory.headers[paging.TOTAL_HEADER] == "5"


def test_a_standards_clause_list_pages():
    doc = _standard(_doc("doc_std"))
    for i in range(4):
        _chunk(
            f"c{i}",
            doc,
            "The coat shall be dry.",
            section=f"5.{i} Part",
            page=i + 1,
            ordinal=i,
        )
    client = _client(doc)
    whole = client.get(f"/api/standards/{doc}/clauses").json()
    page = client.get(f"/api/standards/{doc}/clauses?limit=2&offset=1")
    assert page.json() == whole[1:3]
    assert page.headers[paging.TOTAL_HEADER] == "4"
    requirements = client.get(f"/api/standards/{doc}/requirements?limit=5")
    assert requirements.status_code == 200
    assert requirements.headers[paging.TOTAL_HEADER] == str(len(requirements.json()))


def test_a_bad_page_is_refused():
    doc = _standard(_doc("doc_std"))
    client = _client(doc)
    for path in (
        "/api/standards",
        "/api/standards/inventory",
        f"/api/standards/{doc}/clauses",
    ):
        for query in ("limit=0", "limit=1001", "offset=-1"):
            assert client.get(f"{path}?{query}").status_code == 422, (path, query)


def test_a_browser_on_the_dev_server_may_read_the_total():
    doc = _standard(_doc("doc_std"))
    got = _client(doc).get(
        "/api/standards", headers={"Origin": "http://localhost:5173"}
    )
    exposed = got.headers.get("access-control-expose-headers", "")
    assert paging.TOTAL_HEADER.lower() in exposed.lower()
