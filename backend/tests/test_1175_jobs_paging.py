"""Order 117 item 5: `GET /api/jobs` says how many jobs it left out.

The list was already cut at 100 with nothing to say so: a silent loss. It
still returns 100 by default, newest first, and now carries `total` (every
job the caller may read under the same filter) plus `limit`/`offset` to page
through the rest.

Invented documents and jobs only.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import access, db
from app.main import app
from tests.test_crs_endpoint import _submittal, temp_db  # noqa: F401 - fixture

NOW = "2026-10-18T00:00:00Z"


def _jobs(doc_id: str, n: int, state: str = "done") -> None:
    with db.connect() as conn:
        for i in range(n):
            conn.execute(
                "INSERT INTO jobs (id,document_id,stage,state,started_at,updated_at)"
                " VALUES (?,?,'extract',?,?,?)",
                (f"job_{doc_id}_{state}_{i:03d}", doc_id, state, NOW, NOW),
            )


def _client(*allowed: str) -> TestClient:
    app.dependency_overrides[access.current_scope] = lambda: access.AccessScope(
        user_id="eng", allowed_document_ids=frozenset(allowed)
    )
    return TestClient(app, base_url="http://localhost")


def test_the_default_page_is_100_and_says_how_many_there_are():
    doc = _submittal()
    _jobs(doc, 105)
    body = _client(doc).get("/api/jobs").json()
    assert len(body["jobs"]) == 100
    assert body["total"] == 105 and body["limit"] == 100 and body["offset"] == 0


def test_pages_cover_every_job_once():
    doc = _submittal()
    _jobs(doc, 7)
    client = _client(doc)
    seen = [
        j["id"]
        for o in (0, 3, 6)
        for j in client.get(f"/api/jobs?limit=3&offset={o}").json()["jobs"]
    ]
    assert sorted(seen) == sorted(set(seen)) and len(seen) == 7


def test_the_total_counts_only_readable_jobs_under_the_filter():
    doc = _submittal()
    other = _submittal("doc_other", "other.pdf")
    _jobs(doc, 2)
    _jobs(doc, 1, state="queued")
    _jobs(other, 4)
    assert _client(doc).get("/api/jobs?limit=1").json()["total"] == 3
    assert _client(doc).get("/api/jobs?state=queued").json()["total"] == 1
    narrowed = _client(doc).get(f"/api/jobs?document_id={other}").json()
    assert narrowed == {"jobs": [], "total": 0, "limit": 100, "offset": 0}
    assert _client().get("/api/jobs").json()["total"] == 0


def test_a_bad_page_is_refused():
    client = _client(_submittal())
    for query in ("limit=0", "limit=1001", "offset=-1", "page=2"):
        assert client.get(f"/api/jobs?{query}").status_code == 422, query
