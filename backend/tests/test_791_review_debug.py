"""#791 part 0: REVIEW_DEBUG prints every review step to the backend console
and to a git-ignored per-run log, through the `review.debug` logger.

Debug on: every one of the ten steps writes its line; detail adds item lines.
Debug off: nothing printed or written. Either way the result is the same: the
trace only reads what the run stored. Invented documents only.
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from app import access, db, review_jobs, review_trace
from app.config import settings
from tests.test_p3_review_jobs import W, _enqueue, temp_storage, world  # noqa: F401


def _finished_run(world):
    run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    assert review_jobs.run(job_id, W) == "done"
    return run_id


def _scope(world):
    return access.AccessScope(user_id="adm", allowed_document_ids=world["scope"])


def _findings(run_id):
    return sorted((tuple(str(x) for x in r) for r in db.connect().execute(
        "SELECT requirement_id, compliance_status, fact_id FROM review_findings"
        " WHERE review_run_id = ?", (run_id,))))


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_debug_on_prints_every_step_to_the_console_and_the_run_file(world, monkeypatch):
    """THE MUTATION TARGET: each of the ten steps writes its block line."""
    monkeypatch.setattr(settings, "review_debug", True)
    capture = _Capture()
    logging.getLogger(review_trace.LOGGER_NAME).addHandler(capture)
    try:
        run_id = _finished_run(world)
    finally:
        logging.getLogger(review_trace.LOGGER_NAME).removeHandler(capture)
    steps = [line for line in capture.lines if line.startswith("[")]
    assert [line.split("]")[0].split(" ", 1)[1] for line in steps] == list(review_trace.STEPS)
    assert capture.lines[0].startswith(f"=== REVIEW {run_id}")
    assert any("fails 1" in line for line in steps), "the decide step names the verdict"
    log_file = review_trace.debug_dir() / f"review-{run_id}.log"
    assert log_file.read_text(encoding="utf-8").splitlines() == capture.lines


def test_detail_adds_one_line_per_item(world, monkeypatch):
    run_id = _finished_run(world)
    monkeypatch.setattr(settings, "review_debug", True)
    plain = review_trace.emit(run_id, _scope(world))
    monkeypatch.setattr(settings, "review_debug_detail", True)
    detailed = review_trace.emit(run_id, _scope(world))
    items = [line for line in detailed if line.startswith("      - ")]
    assert items and len(detailed) == len(plain) + len(items)
    assert any("Noise level" in line for line in items), "the READ items list the values with page"


def test_debug_off_prints_and_writes_nothing(world):
    assert settings.review_debug is False, "off by default"
    run_id = _finished_run(world)
    assert review_trace.emit(run_id, _scope(world)) is None
    assert not (review_trace.debug_dir() / f"review-{run_id}.log").exists()


def test_the_trace_never_changes_the_result(world, monkeypatch):
    run_id = _finished_run(world)
    before = _findings(run_id)
    monkeypatch.setattr(settings, "review_debug", True)
    monkeypatch.setattr(settings, "review_debug_detail", True)
    review_trace.emit(run_id, _scope(world))
    assert _findings(run_id) == before


def test_a_failing_trace_never_breaks_the_review(world, monkeypatch):
    monkeypatch.setattr(settings, "review_debug", True)
    monkeypatch.setattr(review_trace, "build", lambda *a, **k: 1 / 0)
    _finished_run(world)  # still "done"


def test_the_debug_logger_does_not_reach_the_server_log():
    assert logging.getLogger(review_trace.LOGGER_NAME).propagate is False


def test_the_per_run_log_folder_is_git_ignored():
    repo = Path(__file__).resolve().parents[2]
    path = (Path("backend") / "data" / "debug" / "review-x.log").as_posix()
    assert subprocess.run(["git", "check-ignore", "-q", path], cwd=repo).returncode == 0
    assert review_trace.debug_dir() == Path(settings.data_dir) / "debug"

