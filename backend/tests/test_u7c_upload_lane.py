"""Update 7, builder C (planner 19 Nov 2026 01:02, GitHub #1913): an upload never waits behind a running review.

The worker runs an upload lane and a review lane on two threads; one large local model at a time between them
(`local_model_gate`). Invented documents only; no model is run.
"""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient

from app import (
    agent_review_jobs,
    aim_review_jobs,
    db,
    ingest,
    local_model_gate,
    review_jobs,
)
from app.main import app
from tests.test_worker_health import temp_storage, upload  # noqa: F401 - fixture


def _wait(cond, seconds: float = 60.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _status(doc_id: str) -> str:
    return (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc_id,))
        .fetchone()["status"]
    )


def test_an_upload_is_read_to_the_end_while_a_review_is_running(
    temp_storage, monkeypatch
):  # noqa: F811
    started, release = threading.Event(), threading.Event()
    claims = {"n": 0}

    def claim(_worker_id):
        claims["n"] += 1
        return "job-review-1" if claims["n"] == 1 else None

    def long_review(job_id, worker_id, heartbeat=None):
        started.set()
        release.wait(120)  # a paid review that runs for minutes
        return "done"

    for mod in (review_jobs, agent_review_jobs, aim_review_jobs):
        monkeypatch.setattr(mod, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", claim)
    monkeypatch.setattr(review_jobs, "run", long_review)
    monkeypatch.setattr(agent_review_jobs, "claim_next", lambda _w: None)
    monkeypatch.setattr(aim_review_jobs, "claim_next", lambda _w: None)

    w = ingest.IngestionWorker(poll_seconds=0.05)
    w.start()
    try:
        assert started.wait(30), "the review never started"
        doc = upload(TestClient(app), name="lane.pdf")
        assert _wait(lambda: _status(doc) == "ready"), _status(doc)
        assert (
            w.reviewing is True and not release.is_set()
        )  # read to the end while the review still runs
        assert w.status()["uploads_waiting_for_review"] == 0
    finally:
        release.set()
        w.stop(timeout=10)
    assert w.reviewing is False


def test_the_gate_lets_one_lane_hold_the_local_model_and_the_other_waits():
    order: list[str] = []
    holding, done = threading.Event(), threading.Event()

    def review_call():
        with local_model_gate.lane(local_model_gate.REVIEW), local_model_gate.holding():
            order.append("review in")
            holding.set()
            done.wait(10)
            order.append("review out")

    def upload_call():
        with local_model_gate.lane(local_model_gate.UPLOAD), local_model_gate.holding():
            order.append("upload in")

    r = threading.Thread(target=review_call)
    r.start()
    assert holding.wait(5)
    u = threading.Thread(target=upload_call)
    u.start()
    assert _wait(
        lambda: local_model_gate.blocked(local_model_gate.UPLOAD), 5
    )  # waits while the review holds the model
    assert order == ["review in"]
    done.set()
    r.join(5)
    u.join(5)
    assert order == ["review in", "review out", "upload in"]
    assert not local_model_gate.blocked(local_model_gate.UPLOAD)


def test_calls_of_one_lane_share_the_model_and_a_waiting_lane_goes_next():
    first_in, release = threading.Event(), threading.Event()
    order: list[str] = []

    def review(tag: str, hold: bool):
        with local_model_gate.lane(local_model_gate.REVIEW), local_model_gate.holding():
            order.append(tag)
            if hold:
                first_in.set()
                release.wait(10)

    a = threading.Thread(target=review, args=("review 1", True))
    a.start()
    assert first_in.wait(5)
    b = threading.Thread(
        target=review, args=("review 2", False)
    )  # same lane, no other lane waiting: shares the model
    b.start()
    b.join(5)
    assert order == ["review 1", "review 2"]

    def upload_call():
        with local_model_gate.lane(local_model_gate.UPLOAD), local_model_gate.holding():
            order.append("upload")

    up = threading.Thread(target=upload_call)
    up.start()
    assert _wait(lambda: local_model_gate.blocked(local_model_gate.UPLOAD), 5)
    c = threading.Thread(
        target=review, args=("review 3", False)
    )  # the upload lane waits: the review lane starts no new call
    c.start()
    time.sleep(0.2)
    assert "review 3" not in order
    release.set()
    for t in (a, up, c):
        t.join(5)
    assert order.index("upload") < order.index("review 3")


def test_a_call_outside_the_worker_is_never_gated():
    with local_model_gate.lane(local_model_gate.REVIEW), local_model_gate.holding():
        seen = []
        t = threading.Thread(target=lambda: seen.append(local_model_gate.current()))
        t.start()
        t.join(5)
        with local_model_gate.holding():  # same lane again, nobody waiting: passes
            seen.append("passed")
    assert seen == [None, "passed"]  # a plain thread (a chat request) is in no lane


def test_uploads_waiting_for_the_model_are_reported_while_the_review_holds_it(
    temp_storage, monkeypatch
):  # noqa: F811
    upload(TestClient(app), name="waiting.pdf")
    w = ingest.IngestionWorker()
    alive = type("T", (), {"is_alive": staticmethod(lambda: True)})
    w._thread, w._review_thread = alive(), alive()
    w.reviewing, w.last_review_beat = True, time.time()
    monkeypatch.setattr(
        local_model_gate, "blocked", lambda lane: lane == local_model_gate.UPLOAD
    )
    s = w.status()
    assert s["uploads_waiting_for_review"] == s["pending_count"] >= 1
    assert not any(r.startswith("no_heartbeat") for r in s["stalled_reasons"])
