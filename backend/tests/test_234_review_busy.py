"""Order 234: a long review step is not "Queue not moving".

The sidebar shows the red badge when health says `stalled` and not `busy`. A
review job runs on the ingestion worker's one thread (a 35B-model page can take
a minute and a half), so documents queued behind it made `stalled` true while
`busy` stayed false (only a document set it). A running review is now work:
health says `busy`, its progress updates count as a heartbeat and as progress,
and the queue behind it is not "ignored". A queue that is truly stuck with no
review running still reads as stalled. Invented queue; no model is run.
"""

import time

from fastapi.testclient import TestClient

from app import dashboard_pool, ingest, job_queue, review_jobs
from app.ingest import NO_PROGRESS_SECONDS, STALL_AFTER_SECONDS, IngestionWorker
from app.main import app
from app.worker_review import REVIEW_SILENCE_SECONDS
from tests.test_worker_health import temp_storage, upload  # noqa: F401


def _alive_worker_with_a_backlog(monkeypatch):
    """An alive worker, a document waiting, nothing finished for a long time."""
    TestClient(app)
    upload(TestClient(app))
    w = IngestionWorker()
    w._thread = type("T", (), {"is_alive": staticmethod(lambda: True)})()
    w.last_beat = time.time()
    w.last_progress = time.time() - (NO_PROGRESS_SECONDS + 10)
    monkeypatch.setattr(ingest, "get_worker", lambda: w)
    dashboard_pool._health.clear()
    return w


def _health():
    dashboard_pool._health.clear()
    return TestClient(app).get("/api/health").json()["ingestion"]


def _badge_is_red(ingestion: dict) -> bool:
    """`Shell.tsx`: "Queue not moving" iff stalled and not busy."""
    return ingestion["stalled"] and not ingestion["busy"]


def test_a_queue_with_no_review_running_is_still_not_moving(monkeypatch):
    _alive_worker_with_a_backlog(monkeypatch)
    assert _badge_is_red(_health())


def test_a_slow_review_step_is_busy_not_stuck(monkeypatch):
    w = _alive_worker_with_a_backlog(monkeypatch)
    seen = {}

    def slow_step(job_id, worker_id, heartbeat=None):
        # The step does not report for a long while (a 35B-model page).
        w.last_beat = time.time() - (STALL_AFTER_SECONDS + 60)
        seen["health"] = _health()
        seen["status"] = w.status()
        return "done"

    monkeypatch.setattr(review_jobs, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", lambda worker: "job-1")
    monkeypatch.setattr(review_jobs, "run", slow_step)
    monkeypatch.setattr(job_queue, "worker_id", lambda: "w1")
    assert w._drain_review_jobs() is True

    assert seen["health"]["busy"] is True
    assert not _badge_is_red(seen["health"])
    assert not any(
        "pending_but_no_progress" in r for r in seen["status"]["stalled_reasons"]
    )
    assert seen["status"]["reviewing"] is True


def test_a_review_that_reports_nothing_for_a_long_time_turns_red_again(monkeypatch):
    """cloud's ask on #1323: `busy` for a review is bounded by the silence, so a
    review stuck forever in a model call is not hidden behind "busy"."""
    w = _alive_worker_with_a_backlog(monkeypatch)
    seen = {}

    def stuck(job_id, worker_id, heartbeat=None):
        w.last_beat = time.time() - (REVIEW_SILENCE_SECONDS + 60)
        seen["health"] = _health()
        w.last_beat = time.time() - (REVIEW_SILENCE_SECONDS - 120)
        seen["quiet_but_alive"] = _health()
        return "done"

    monkeypatch.setattr(review_jobs, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", lambda worker: "job-1")
    monkeypatch.setattr(review_jobs, "run", stuck)
    monkeypatch.setattr(job_queue, "worker_id", lambda: "w1")
    assert w._drain_review_jobs() is True
    assert _badge_is_red(seen["health"])
    assert not _badge_is_red(seen["quiet_but_alive"])


def test_the_queue_is_not_called_stuck_the_moment_a_review_ends(monkeypatch):
    w = _alive_worker_with_a_backlog(monkeypatch)
    monkeypatch.setattr(review_jobs, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", lambda worker: "job-1")
    monkeypatch.setattr(review_jobs, "run", lambda *a, **k: "done")
    monkeypatch.setattr(job_queue, "worker_id", lambda: "w1")
    assert w._drain_review_jobs() is True
    assert w.reviewing is False
    assert not _badge_is_red(_health())


def test_a_review_that_fails_still_clears_busy(monkeypatch):
    w = _alive_worker_with_a_backlog(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(review_jobs, "recover_stale", lambda: None)
    monkeypatch.setattr(review_jobs, "claim_next", lambda worker: "job-1")
    monkeypatch.setattr(review_jobs, "run", boom)
    monkeypatch.setattr(job_queue, "worker_id", lambda: "w1")
    assert w._drain_review_jobs() is False
    assert w.reviewing is False


def test_a_review_progress_update_counts_as_worker_activity():
    w = IngestionWorker()
    w.last_beat = w.last_progress = time.time() - 1000
    beats = []
    review_jobs._page(
        _NoTransaction(), "j", 3, 11, heartbeat=lambda: beats.append("page")
    )
    review_jobs._step(_StepConn(), "j", 1, heartbeat=lambda: beats.append("step"))
    assert beats == ["page", "step"]
    w._review_activity()
    assert time.time() - w.last_beat < 5 and time.time() - w.last_progress < 5


class _NoTransaction:
    """A connection mid-transaction: the progress line is skipped, the beat is not."""

    in_transaction = True


class _StepConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self

    def fetchone(self):
        return None


def test_a_model_call_is_a_beat_at_both_ends_while_a_review_runs(monkeypatch):
    from app import model_transport, worker_review
    from app.reasoning_provider import OllamaProvider, Packet

    monkeypatch.setattr(
        model_transport,
        "post_json",
        lambda path, body, timeout: {"response": "{}", "model": "m"},
    )
    beats = []
    provider = OllamaProvider("m", timeout=5)
    packet = Packet(prompt="p", num_ctx=1024, num_predict=16)
    provider.reason(packet)
    assert beats == []  # no review running on this thread: nothing beats
    token = worker_review._ACTIVITY.set(lambda: beats.append(1))
    try:
        provider.reason(packet)
    finally:
        worker_review._ACTIVITY.reset(token)
    assert len(beats) == 2


def test_a_dead_worker_thread_is_not_busy():
    w = IngestionWorker()  # no thread started: not alive
    w.reviewing = True
    w.last_beat = time.time()
    assert w.in_review() is False
