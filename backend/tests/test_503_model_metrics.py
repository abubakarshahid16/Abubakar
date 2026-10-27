"""#503: per-model latency and error counts, stored per review run.

A stubbed transport stands in for the engine; no model is asked. Counts and seconds only:
no prompt, answer or exception message is stored.
"""

from __future__ import annotations

import json

import pytest

from app import db, ingest, job_queue, model_metrics, model_transport, review_jobs
from app.reasoning_provider import OllamaProvider, Packet, ProviderRefused
from app.worker_review import ReviewDrain  # noqa: F401 - the mixin under test
from tests import test_p3_review_jobs as p3

world, temp_storage = p3.world, p3.temp_storage  # the review-job fixtures
PACKET = Packet(prompt="SECRET PROMPT TEXT", num_ctx=1024, num_predict=16)


def _stub(monkeypatch, outcomes):
    """post_json answers from `outcomes` in order: a dict is an answer, an exception is raised."""
    calls = iter(outcomes)

    def post(path, body, timeout):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(model_transport, "post_json", post)


def test_calls_are_noted_per_model_with_seconds_and_error_kinds(monkeypatch):
    _stub(
        monkeypatch,
        [
            {"response": "SECRET ANSWER", "model": "m1"},
            RuntimeError("SECRET MESSAGE"),
            {"response": "{}"},
        ],
    )
    with model_metrics.collect() as bucket:
        OllamaProvider("model-a", timeout=5).reason(PACKET)
        with pytest.raises(ProviderRefused):
            OllamaProvider("model-a", timeout=5).reason(PACKET)
        OllamaProvider("model-b", timeout=5).reason(PACKET)
    assert set(bucket) == {"model-a", "model-b"}
    a = bucket["model-a"]
    assert (a["calls"], a["errors"], a["kinds"]) == (2, 1, {"RuntimeError": 1})
    assert a["seconds"] >= 0 and a["longest"] <= a["seconds"] + 1e-9
    assert (bucket["model-b"]["calls"], bucket["model-b"]["errors"]) == (1, 0)
    assert "SECRET" not in json.dumps(bucket)  # no prompt, answer or message


def test_nothing_is_noted_outside_a_review(monkeypatch):
    _stub(monkeypatch, [{"response": "x"}])
    OllamaProvider("model-a", timeout=5).reason(PACKET)  # no bucket: a no-op, no error
    assert model_metrics._BUCKET.get() is None


def test_a_bucket_is_stored_per_run_and_model_with_the_date(world):
    run_id, _job = p3._enqueue(world)
    bucket = {
        "model-a": {
            "calls": 3,
            "errors": 1,
            "seconds": 7.5,
            "longest": 4.0,
            "kinds": {"TimeoutError": 1},
        }
    }
    model_metrics.store(run_id, bucket)
    [row] = model_metrics.for_run(run_id)
    assert (row["model"], row["calls"], row["errors"]) == ("model-a", 3, 1)
    assert (row["seconds_total"], row["seconds_longest"]) == (7.5, 4.0)
    assert (
        row["error_kinds"] == {"TimeoutError": 1}
        and row["day"]
        and row["gold_score"] is None
    )


def test_storing_never_raises_into_the_review(world):
    model_metrics.store(
        None, {"m": {"calls": 1, "errors": 0, "seconds": 1, "longest": 1, "kinds": {}}}
    )
    model_metrics.store("no-such-run", {})
    with db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS model_call_metrics")
        conn.execute("CREATE TABLE model_call_metrics (x TEXT)")  # a broken table
    model_metrics.store(
        "run", {"m": {"calls": 1, "errors": 0, "seconds": 1, "longest": 1, "kinds": {}}}
    )


def test_the_worker_stores_the_calls_of_a_review_run_even_when_the_run_fails(
    world, monkeypatch
):
    run_id, job_id = p3._enqueue(world)

    def run(job, worker, heartbeat=None):
        OllamaProvider("model-a", timeout=5).reason(PACKET)
        raise RuntimeError("the review failed")

    _stub(monkeypatch, [{"response": "{}"}])
    monkeypatch.setattr(review_jobs, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", lambda worker: job_id)
    monkeypatch.setattr(review_jobs, "run", run)
    monkeypatch.setattr(job_queue, "worker_id", lambda: p3.W)
    worker = ingest.IngestionWorker()
    assert worker._drain_review_jobs() is False  # the failure is recorded by the worker
    [row] = model_metrics.for_run(run_id)
    assert (row["model"], row["calls"], row["errors"]) == ("model-a", 1, 0)
