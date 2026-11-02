"""#1494: the progress block of a running review, from the jobs row only."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app import db, job_queue, review_jobs
from app.config import settings
from tests.test_crs_endpoint import (  # noqa: F401 - fixture
    NOW,
    _run,
    _submittal,
    temp_db,
)


def _stamp(seconds_ago: int) -> str:
    return (
        (datetime.now(UTC) - timedelta(seconds=seconds_ago))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _job(label: str, *, started=600, updated=30, claimed=30, state="running"):
    doc = _submittal()
    run_id = _run(doc)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at, claimed_at,"
            " review_run_id, progress_done, progress_total, progress_label)"
            " VALUES ('j1', ?, 'review', ?, ?, ?, ?, ?, 0, 3, ?)",
            (
                doc,
                state,
                _stamp(started),
                _stamp(updated),
                _stamp(claimed),
                run_id,
                label,
            ),
        )
    return run_id


def test_switch_off_the_job_carries_no_progress_detail(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", False)
    run_id = _job("reading the datasheet, page 7 of 69")
    assert "progress_detail" not in review_jobs.job_for_run(run_id)


def test_pages_done_are_finished_pages_not_the_page_started(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("reading the datasheet, page 7 of 69")
    d = review_jobs.job_for_run(run_id)["progress_detail"]
    assert (d["pages_done"], d["pages_total"]) == (6, 69)
    assert 590 <= d["elapsed_seconds"] <= 620
    assert d["stale"] is False


def test_outside_the_reading_step_pages_are_null_never_zero(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("comparing requirements with the datasheet")
    d = review_jobs.job_for_run(run_id)["progress_detail"]
    assert d["pages_done"] is None and d["pages_total"] is None


def test_stale_follows_the_job_queue_rule_and_idle_is_the_newest_movement(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job(
        "reading the datasheet, page 2 of 9",
        updated=job_queue.CLAIM_STALE_SECONDS + 30,
        claimed=job_queue.CLAIM_STALE_SECONDS + 60,
    )
    d = review_jobs.job_for_run(run_id)["progress_detail"]
    # Stale only when the line has not moved for as long either (live I-06).
    assert d["stale"] is True
    newest = job_queue.CLAIM_STALE_SECONDS + 30
    assert newest - 5 <= d["idle_seconds"] <= newest + 10


def test_a_finished_job_has_no_progress_detail(monkeypatch):
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    run_id = _job("done", state="done")
    assert "progress_detail" not in review_jobs.job_for_run(run_id)
