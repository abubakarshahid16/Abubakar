"""#626: the health-under-load measuring tool reports honestly - a failed call
is counted, never timed as a success; the job always ends the probing; and it
never runs on the live database. Invented jobs and clients only."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import measure_health_under_load as m  # noqa: E402


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


class _Client:
    """200, then 503, then 200 ... - stands in for the app."""

    def __init__(self):
        self.calls = 0

    def get(self, path):
        assert path == "/api/health"
        self.calls += 1
        return _Response(503 if self.calls % 2 == 0 else 200)


def test_the_summary_is_median_p95_and_slowest():
    out = m.summarise([0.1, 0.3, 0.2, 0.4, 5.0])
    assert out == {"calls": 5, "median_s": 0.3, "p95_s": 5.0, "max_s": 5.0}
    assert m.summarise([]) == {"calls": 0}


def test_a_failed_call_is_counted_not_timed_and_a_job_error_is_reported():
    client = _Client()

    def job():
        time.sleep(0.25)
        raise RuntimeError("the scan stopped")

    out = m.probe_while(client, job, every=0.05)
    assert out["non_200"] >= 1 and out["calls"] >= 1
    assert out["calls"] + out["non_200"] == client.calls       # every call accounted for once
    assert out["job_error"] == "RuntimeError"


def test_a_quick_job_is_still_probed_once():
    client = _Client()
    out = m.probe_while(client, lambda: None, every=0.05)
    assert client.calls >= 1 and out["calls"] + out["non_200"] == client.calls
    assert out["job_error"] is None


def test_it_refuses_a_live_shaped_database_path(tmp_path, monkeypatch):
    for name in ("DB_PATH", "DATA_DIR", "AUTH_MODE", "STARTUP_WARMUP"):
        monkeypatch.delenv(name, raising=False)       # restored after the test
    live = tmp_path / "backend" / "data" / "rag_intelligence.sqlite"
    live.parent.mkdir(parents=True)
    with pytest.raises(SystemExit, match="refusing"):
        m.main(["--db", str(live)])
    assert not live.exists()
