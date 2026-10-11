"""#791 parts 1-3: the review run's step-by-step trace, stored per run, behind
the run's access rules, served by an API route and as a JSON download.

What must hold: every finished run stores all ten steps, each with a status
and its phase timing, plus the run's AI use; the stored trace is served only
to a caller who may read every document it names - any other reader of the
run gets the steps built now under their own access, and a non-reader gets
404; the route is read only; the trace never changes or breaks a review.
Synthetic documents only.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app import main, review_jobs, review_trace
from app.db import connect
from app.main import app
from tests.test_p3_review_jobs import W, _enqueue, _user, temp_storage, world  # noqa: F401 - fixtures


def _reviewed(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _get(world, run_id, headers=None, **params):
    return TestClient(app).get(f"/api/reviews/runs/{run_id}/trace",
                               headers=headers or world["admin"], params=params)


def test_every_finished_run_stores_all_ten_steps_with_status_and_timing(world):
    run_id = _reviewed(world)
    row = connect().execute("SELECT trace FROM review_run_traces WHERE review_run_id = ?",
                            (run_id,)).fetchone()
    trace = json.loads(row["trace"])
    assert [s["step"] for s in trace["steps"]] == list(review_trace.STEPS)
    for step in trace["steps"]:
        assert step["status"] in ("ok", "warning", "failed")
        assert step["timing"]["seconds"] >= 0 and step["timing"]["started_at"]
    assert "ai_engineering_check" in trace["ai"]
    assert set(trace["document_ids"]) >= {world["sub"], world["std"]}


def test_the_route_serves_the_stored_trace_without_its_internal_fields(world):
    run_id = _reviewed(world)
    r = _get(world, run_id)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "stored when the review finished" and body["stored_at"]
    assert len(body["steps"]) == 10 and "document_ids" not in body
    decide = next(s for s in body["steps"] if s["step"] == "DECIDE")
    assert decide["counts"]["fails"] >= 1


def test_the_download_is_the_same_trace_as_a_file(world):
    run_id = _reviewed(world)
    r = _get(world, run_id, download="true")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == f'attachment; filename="review-trace-{run_id}.json"'
    assert json.loads(r.content)["steps"] == _get(world, run_id).json()["steps"]


def test_a_reader_without_every_grant_gets_a_trace_built_under_their_access(world):
    run_id = _reviewed(world)
    sub_only = _user("subonly", [world["sub"]])
    body = _get(world, run_id, headers=sub_only).json()
    assert body["source"].startswith("built now under your access")
    assert "std_api" not in json.dumps(body)
    stranger = _user("stranger", [])
    assert _get(world, run_id, headers=stranger).status_code == 404


def test_the_route_is_read_only(world):
    run_id = _reviewed(world)
    with connect() as conn:
        conn.execute("DROP TABLE review_run_traces")
    body = _get(world, run_id).json()
    assert body["source"].startswith("built now")
    assert connect().execute("SELECT 1 FROM sqlite_master WHERE name = 'review_run_traces'"
                             ).fetchone() is None
    assert _get(world, run_id, unknown="x").status_code == 422


def test_a_step_that_could_not_be_built_is_marked_failed(world, monkeypatch):
    run_id = _reviewed(world)

    def boom(*a, **k):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(main, "_crs_content", boom)
    trace = review_trace.store(run_id, main.access.AccessScope(
        user_id="adm", allowed_document_ids=world["scope"]))
    crs = next(s for s in trace["steps"] if s["step"] == "CRS")
    assert crs["status"] == "failed" and crs["warning"] == "CRS not composed"


def test_the_trace_never_changes_or_breaks_a_review(world, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("synthetic trace failure")
    monkeypatch.setattr(review_trace, "build", boom)
    run_id = _reviewed(world)     # still "done"
    statuses = sorted(r[0] for r in connect().execute(
        "SELECT compliance_status FROM review_findings WHERE review_run_id = ?", (run_id,)))
    assert "NON_COMPLIANT" in statuses
    scope = main.access.AccessScope(user_id="adm", allowed_document_ids=world["scope"])
    assert review_trace.stored(run_id, scope) is None
