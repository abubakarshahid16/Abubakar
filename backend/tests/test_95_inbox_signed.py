"""Order 95 piece 3: the inbox's "Signed" comes from the stored issue record.

`crs_issued_at` on each run in `GET /api/reviews/runs` is when the newest
contractor copy was issued, and null - never a guess - when none was. A run
whose engineer chose a final code but issued nothing is not signed.

Invented runs and findings only.
"""

from __future__ import annotations

from tests.test_885_crs_issue_gate import _fid, _issue, _run
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    _client,
    _finding,
    _submittal,
    temp_db,
)


def _listed(client, run_id):
    r = client.get("/api/reviews/runs")
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["runs"] if x["review_run_id"] == run_id)


def test_a_run_with_no_issued_copy_is_not_signed_even_with_a_final_code():
    doc = _submittal()
    run = _run(doc, final_code="Approved")
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc)
    assert _listed(client, run)["crs_issued_at"] is None


def test_issuing_the_contractor_copy_marks_the_run_signed_with_the_issue_time():
    doc = _submittal()
    run = _run(doc)
    _finding(doc, run, "NON_COMPLIANT")
    client = _client(doc)
    decided = client.post(
        f"/api/reviews/runs/{run}/crs/open-items/findings/{_fid(run)}/decision",
        json={"decision": "accept", "reason": "breach confirmed against clause 6.2.2"},
    )
    assert decided.status_code == 200, decided.text
    assert _issue(client, run).status_code == 200

    copies = client.get(f"/api/reviews/runs/{run}/crs/issued").json()["copies"]
    assert _listed(client, run)["crs_issued_at"] == copies[0]["issued_at"]
