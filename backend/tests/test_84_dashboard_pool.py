"""Order 84-1 (#626 follow-up): slow dashboard reads can no longer starve the
server's shared thread pool, and /api/health never waits for a thread.

Measured in the owner's app while a review ran: /api/health 52 s, behind
/api/risks, /api/metrics and /api/reviews/runs. Health does almost nothing; it
was queued for one of the 40 shared worker threads.
"""
from __future__ import annotations

import inspect
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import access, dashboard_pool, db
from app import main as main_mod
from app.api import run_summary as api_run_summary
from app.config import settings


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "u")
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _client():
    return TestClient(main_mod.app, base_url="http://127.0.0.1")


def test_health_runs_on_the_event_loop_and_the_dashboard_reads_do_not():
    assert inspect.iscoroutinefunction(main_mod.health)
    for route in (
        main_mod.metrics,
        main_mod.list_risks,
        api_run_summary.list_review_runs,
    ):
        assert inspect.iscoroutinefunction(route), route.__name__
        assert route.__wrapped__.__name__ == route.__name__


def test_health_answers_while_slow_dashboard_reads_hold_every_shared_thread(monkeypatch):
    """The shared pool is shrunk to 3 threads and 4 dashboard reads are held
    open; before #84-1 health queued behind them."""
    import anyio.to_thread

    release = threading.Event()
    # The read GET /api/risks really makes (88a: list_page -> _read_page). Patching
    # list_items held nothing and let this test pass on the unfixed code (cloud-2's review).
    real = main_mod.risks_mod._read_page
    started = threading.Semaphore(0)

    def held(*a, **k):
        started.release()
        release.wait(10)
        return real(*a, **k)

    monkeypatch.setattr(main_mod.risks_mod, "_read_page", held)
    with _client() as client:
        async def shrink():
            limiter = anyio.to_thread.current_default_thread_limiter()
            before, limiter.total_tokens = limiter.total_tokens, 3
            return before

        before = client.portal.call(shrink)
        try:
            # four distinct questions (single-flight must not merge them) for 3 shared threads
            readers = [threading.Thread(target=client.get, args=("/api/risks",), kwargs={
                "params": {"risk_type": t}}) for t in ("schedule", "review", "dependency", "compliance")]
            for r in readers:
                r.start()
            for _ in range(3):  # three readers inside the held read: the shrunk pool is full
                assert started.acquire(timeout=5)
            started = time.perf_counter()
            assert client.get("/api/health").status_code == 200
            assert time.perf_counter() - started < 2.0
        finally:
            release.set()
            for r in readers:
                r.join(10)

            async def restore():
                anyio.to_thread.current_default_thread_limiter().total_tokens = before

            client.portal.call(restore)


def test_identical_dashboard_reads_in_flight_share_one_computation(monkeypatch):
    calls = []
    gate = threading.Event()
    real = main_mod.metrics_mod.snapshot

    def counted(*a, **k):
        calls.append(1)
        gate.wait(5)
        return real(*a, **k)

    monkeypatch.setattr(main_mod.metrics_mod, "snapshot", counted)
    with _client() as client:
        results = []
        readers = [threading.Thread(target=lambda: results.append(client.get("/api/metrics")))
                   for _ in range(6)]
        for r in readers:
            r.start()
        time.sleep(0.5)
        gate.set()
        for r in readers:
            r.join(10)
        assert [r.status_code for r in results] == [200] * 6
        assert len(calls) == 1
        # nothing is kept once the call ends: the next poll computes again
        assert client.get("/api/metrics").status_code == 200
        assert len(calls) == 2


def test_an_answer_is_shared_only_with_an_identical_scope():
    a = access.AccessScope(user_id="u1", allowed_document_ids=frozenset({"d1"}))
    b = access.AccessScope(user_id="u2", allowed_document_ids=frozenset({"d1"}))
    c = access.AccessScope(user_id="u1", allowed_document_ids=frozenset({"d1", "d2"}))

    def route(scope, risk_type=None):
        return None

    keys = {dashboard_pool._same_question(route, {"scope": s}) for s in (a, b, c)}
    assert len(keys) == 3
    assert dashboard_pool._same_question(route, {"scope": a}) == \
        dashboard_pool._same_question(route, {"scope": a})
    assert dashboard_pool._same_question(route, {"x": [1]}) is None


def test_health_reuses_a_recent_worker_status(monkeypatch):
    dashboard_pool._health.clear()
    with _client() as client:
        worker = main_mod.ingest_mod.get_worker()
        real, counted = worker.status, []
        monkeypatch.setattr(worker, "status", lambda: counted.append(1) or real())
        for _ in range(5):
            assert client.get("/api/health").status_code == 200
        assert len(counted) == 1
        monkeypatch.setattr(dashboard_pool, "HEALTH_STATUS_MAX_AGE", 0.0)
        client.get("/api/health")
        assert len(counted) == 2                 # older than the limit: asked again
