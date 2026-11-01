"""#1494 follow-up (live I-06 review): one slow page is not a stall.

The amber threshold of a model sub-step allows the model's own time limit, the
block names the sub-step it waits on, and a job whose progress line is moving
is never "stuck". Also: a Word label is read in parts. Invented rows only.
"""

from __future__ import annotations

from app import db, job_queue, review_jobs
from app.config import settings
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


def test_outside_a_model_sub_step_nothing_is_named(monkeypatch):
    d = _detail("selecting the applicable standards", monkeypatch)
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
