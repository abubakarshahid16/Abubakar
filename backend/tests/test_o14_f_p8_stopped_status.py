"""P8 (H's one-real-file pass, 27 Nov 2026): Documents -> Details said "Review status: Review complete" when the paper's newest
review had STOPPED early (a general review ends its job `completed` and keeps `partial` in its outcome). Now it reads `stopped`, and
the date of the newest COMPLETE review is given beside it. Invented values only."""

from __future__ import annotations

import json

from app import db, submittal_review
from tests.test_crs_endpoint import _client, _submittal, temp_db  # noqa: F401 - fixture


def _run(doc: str, run_id: str, at: str, *, partial: bool | None, status: str = "completed") -> None:
    outcome = None if partial is None else json.dumps({"general_review": True, "status": "stopped" if partial else "done", "partial": partial})
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO review_runs (id,submittal_document_id,status,outcome_json,created_at,updated_at,completed_at) VALUES (?,?,?,?,?,?,?)",
            (run_id, doc, status, outcome, at, at, at if status == "completed" else None),
        )


def _status(doc: str) -> str:
    return submittal_review.review_status_for([doc], allowed_document_ids=frozenset({doc}))[doc]


def test_a_stopped_newest_review_is_never_review_complete_and_names_the_last_complete_one():
    doc = _submittal("doc_inv_p8", "invented-p8.pdf")
    _run(doc, "run_inv_done", "2026-11-18T10:00:00+00:00", partial=False)
    _run(doc, "run_inv_stopped", "2026-11-27T05:00:00+00:00", partial=True)
    assert _status(doc) == "stopped"
    client = _client(doc)
    single = client.get(f"/api/documents/{doc}").json()
    listed = next(d for d in client.get("/api/documents").json() if d["id"] == doc)
    for got in (single, listed):
        assert got["review_status"] == "stopped"
        assert got["last_complete_review_at"] == "2026-11-18T10:00:00+00:00"


def test_a_finished_review_is_unchanged_and_an_old_run_without_an_outcome_is_complete():
    done = _submittal("doc_inv_done", "invented-done.pdf")
    _run(done, "run_inv_ok", "2026-11-20T10:00:00+00:00", partial=False)
    old = _submittal("doc_inv_old", "invented-old.pdf")
    _run(old, "run_inv_old", "2026-10-01T10:00:00+00:00", partial=None)  # an earlier engine's run: no `partial` at all
    assert (_status(done), _status(old)) == ("completed", "completed")
    got = _client(done).get(f"/api/documents/{done}").json()
    assert got["last_complete_review_at"] == "2026-11-20T10:00:00+00:00"


def test_only_stopped_runs_means_no_last_complete_review_and_a_failed_run_is_still_failed():
    doc = _submittal("doc_inv_only_stopped", "invented-s.pdf")
    _run(doc, "run_inv_s1", "2026-11-27T05:00:00+00:00", partial=True)
    assert _status(doc) == "stopped"
    assert _client(doc).get(f"/api/documents/{doc}").json()["last_complete_review_at"] is None
    failed = _submittal("doc_inv_failed", "invented-f.pdf")
    _run(failed, "run_inv_f", "2026-11-27T06:00:00+00:00", partial=True, status="failed")
    assert _status(failed) == "failed"


def test_the_last_complete_review_is_only_for_papers_the_caller_may_read():
    doc = _submittal("doc_inv_mine", "invented-m.pdf")
    _run(doc, "run_inv_m", "2026-11-20T10:00:00+00:00", partial=False)
    assert submittal_review.last_complete_review_for([doc], allowed_document_ids=frozenset()) == {}
