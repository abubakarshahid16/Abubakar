"""#1494 follow-up (live Datasheet 1 review): one slow page is not a stall.

The amber threshold of a model sub-step allows the model's own time limit, the
block names the sub-step it waits on, and a job whose progress line is moving
is never "stuck". Also: a Word label is read in parts. Invented rows only.
"""

from __future__ import annotations

import inspect
import threading
import time

from app import db, ingest, job_queue, review_jobs, review_progress, worker_review
from app.config import settings
from app.reasoning_provider import OllamaProvider
from tests.test_1494_progress_detail import _job as _job_row
from tests.test_crs_endpoint import temp_db  # noqa: F401 - fixture


def _detail(label: str, monkeypatch, **ages) -> dict:
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    with db.connect() as conn:  # one job row at a time
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM review_runs")
        conn.execute("DELETE FROM documents")
    run_id = _job_row(label, **ages)
    return review_jobs.job_for_run(run_id)["progress_detail"]


def test_the_block_reads_parts_from_a_word_label(monkeypatch):
    d = _detail("reading the document, part 3 of 5", monkeypatch)
    assert (d["pages_done"], d["pages_total"], d["pages_unit"]) == (2, 5, "part")
    d = _detail("reading the procedure, page 3 of 5", monkeypatch)
    assert d["pages_unit"] == "page"


def test_one_slow_page_is_allowed_the_models_time_and_named(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "ollama")
    d = _detail("reading the procedure, page 3 of 5", monkeypatch, updated=200)
    base = int(settings.review_progress_stall_amber_s)
    assert d["stall_amber_seconds"] == base + 2 * int(
        settings.datasheet_ai_timeout_seconds
    )
    assert d["idle_seconds"] < d["stall_amber_seconds"]  # 200 s on one page: no amber
    assert d["waiting_on"] == "reading page 3 of 5: waiting for the model"


def test_with_the_ai_reader_off_no_model_is_named_and_the_threshold_is_the_base(
    monkeypatch,
):
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    d = _detail("reading the document, part 3 of 5", monkeypatch)
    assert d["waiting_on"] == "reading part 3 of 5"
    assert d["stall_amber_seconds"] == int(settings.review_progress_stall_amber_s)


def test_a_clause_waits_on_the_model_with_the_clause_calls_limit(monkeypatch):
    d = _detail("checking clause 12 of 60", monkeypatch)
    assert d["waiting_on"] == "checking clause 12 of 60: waiting for the model"
    assert d["stall_amber_seconds"] == int(
        settings.review_progress_stall_amber_s
    ) + int(settings.clause_review_call_timeout_s)


def test_outside_a_named_step_nothing_is_named(monkeypatch):
    d = _detail("queued", monkeypatch)
    assert d["waiting_on"] is None
    assert d["stall_amber_seconds"] == int(settings.review_progress_stall_amber_s)


def test_a_moving_job_is_never_stuck_even_with_an_old_claim(monkeypatch):
    old = job_queue.CLAIM_STALE_SECONDS + 60
    d = _detail(
        "reading the procedure, page 40 of 69", monkeypatch, updated=30, claimed=old
    )
    assert d["stale"] is False
    d = _detail(
        "reading the procedure, page 40 of 69", monkeypatch, updated=old, claimed=old
    )
    assert d["stale"] is True


# Review finding on PR 1572: model calls beat the worker, never the jobs row.
COMPARING = "comparing requirements with the document"
FROZEN = 20 * 60  # the row untouched for 20 min, past the claim's 15


def _worker(monkeypatch, *, beat_age: float, reviewing=True, thread=None):
    worker = ingest.IngestionWorker()
    worker._thread = thread or threading.current_thread()
    worker.reviewing = reviewing
    worker.last_beat = time.time() - beat_age
    monkeypatch.setattr(ingest, "_worker", worker)
    return worker


def _held(label: str, monkeypatch, claimed_by: str | None = None) -> dict:
    """A job whose row is frozen, claimed by this thread unless told otherwise."""
    monkeypatch.setattr(settings, "review_progress_bar_enabled", True)
    with db.connect() as conn:
        conn.execute("DELETE FROM jobs")
        conn.execute("DELETE FROM review_runs")
        conn.execute("DELETE FROM documents")
    run_id = _job_row(label, updated=FROZEN, claimed=FROZEN)
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET claimed_by = ? WHERE id = 'j1'",
            (claimed_by or job_queue.worker_id(),),
        )
    return review_jobs.job_for_run(run_id)["progress_detail"]


def test_a_beating_worker_is_never_stuck_on_a_frozen_row(monkeypatch):
    worker = _worker(monkeypatch, beat_age=60)
    d = _held(COMPARING, monkeypatch)
    assert d["stale"] is False
    assert 55 <= d["idle_seconds"] <= 70  # the beat is the newest movement
    # A model call just ended: the beat itself counts, through the real hook.
    worker._review_activity()
    assert _held(COMPARING, monkeypatch)["idle_seconds"] <= 5


def test_a_cut_off_page_with_a_beating_worker_is_not_stuck(monkeypatch):
    _worker(monkeypatch, beat_age=30)
    d = _held("reading the document, page 3 of 5", monkeypatch)
    assert d["stale"] is False and d["idle_seconds"] < d["stall_amber_seconds"]


def test_a_long_model_call_within_the_silence_limit_is_not_stuck(monkeypatch):
    # One uncached answer may run 15-20 min between its two beats.
    _worker(monkeypatch, beat_age=FROZEN)
    assert _held(COMPARING, monkeypatch)["stale"] is False


def test_a_dead_worker_with_a_frozen_row_goes_red(monkeypatch):
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    _worker(monkeypatch, beat_age=1, thread=dead)
    holder = (
        f"w-{job_queue._PROCESS_TOKEN}-{dead.ident}"  # the claim is the dead thread's
    )
    assert _held(COMPARING, monkeypatch, claimed_by=holder)["stale"] is True


def test_a_worker_silent_past_the_limit_goes_red(monkeypatch):
    _worker(monkeypatch, beat_age=worker_review.REVIEW_SILENCE_SECONDS + 60)
    assert _held(COMPARING, monkeypatch)["stale"] is True


def test_a_worker_not_reviewing_does_not_vouch_for_the_job(monkeypatch):
    _worker(monkeypatch, beat_age=1, reviewing=False)
    assert _held(COMPARING, monkeypatch)["stale"] is True


def test_a_beat_for_another_claim_does_not_vouch_for_the_job(monkeypatch):
    # A job a dead process left behind, while this worker reviews another.
    _worker(monkeypatch, beat_age=1)
    assert _held(COMPARING, monkeypatch, claimed_by="w-gone-1")["stale"] is True


def test_the_comparing_step_names_itself_and_allows_a_model_call(monkeypatch):
    d = _detail(COMPARING, monkeypatch)
    assert d["waiting_on"] == COMPARING
    limit = inspect.signature(OllamaProvider.__init__).parameters["timeout"].default
    assert limit == review_progress.MODEL_CALL_LIMIT_S
    assert d["stall_amber_seconds"] == (
        int(settings.review_progress_stall_amber_s) + int(limit)
    )


def test_every_other_running_step_names_itself_too(monkeypatch):
    for label in (
        "reading the procedure",
        "selecting the applicable standards",
        review_jobs.FINISHING,
    ):
        assert _detail(label, monkeypatch)["waiting_on"] == label
