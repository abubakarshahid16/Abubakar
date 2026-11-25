"""A long review step is busy, not stopped: the worker is not "hung" while a review that has reported within the silence limit is running,
and a long Claude call beats the heartbeat while it waits (order 14, update 6; the dashboard said "processing has stopped" while the one
worker thread ran reviews). Invented values; no model is run."""

from __future__ import annotations

import time

from app import worker_review
from app.ingest import STALL_AFTER_SECONDS, IngestionWorker
from app.worker_review import REVIEW_SILENCE_SECONDS
from tests.test_worker_health import temp_storage  # noqa: F401 - fixture


def _worker(beat_age: float, reviewing: bool) -> IngestionWorker:
    w = IngestionWorker()
    w._thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    w.last_beat = w.last_progress = time.time() - beat_age
    w.reviewing = reviewing
    return w


def test_a_review_silent_for_minutes_is_busy_not_hung(temp_storage):  # noqa: F811
    s = _worker(STALL_AFTER_SECONDS + 200, reviewing=True).status()
    assert s["reviewing"] is True and s["stalled"] is False
    assert not any(r.startswith("no_heartbeat") for r in s["stalled_reasons"])


def test_without_a_review_the_same_silence_is_hung(temp_storage):  # noqa: F811
    s = _worker(STALL_AFTER_SECONDS + 200, reviewing=False).status()
    assert s["stalled"] is True and any(
        r.startswith("no_heartbeat") for r in s["stalled_reasons"]
    )


def test_a_review_silent_past_the_limit_is_hung_again(temp_storage):  # noqa: F811
    s = _worker(REVIEW_SILENCE_SECONDS + 60, reviewing=True).status()
    assert s["stalled"] is True and any(
        r.startswith("no_heartbeat") for r in s["stalled_reasons"]
    )


def test_keep_beating_beats_while_a_call_waits_and_stops_after():
    beats = []
    token = worker_review._ACTIVITY.set(lambda: beats.append(time.time()))
    try:
        with worker_review.keep_beating(every=0.02):
            time.sleep(0.15)
        n = len(beats)
        assert n >= 3  # it beat several times while the call waited
        time.sleep(0.1)
        assert len(beats) == n  # and not after the call ended
    finally:
        worker_review._ACTIVITY.reset(token)


def test_keep_beating_does_nothing_when_no_review_is_running():
    import threading

    before = threading.active_count()
    with worker_review.keep_beating(every=0.01):
        assert threading.active_count() == before  # no helper thread
