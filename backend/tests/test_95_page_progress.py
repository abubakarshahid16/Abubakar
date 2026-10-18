"""Order 95 piece 3b: "page x of y" while a review reads its datasheet.

The job's step-1 label names the page the reader is on; the reader reports
every page in reading order, an empty one too; outside a job nothing is
recorded; a failing progress line never stops a reading; and a progress line
never commits the reader's unfinished writes. Synthetic documents only.
"""

from __future__ import annotations

from app import datasheet_ai, db, job_progress, review_jobs, submittal_review
from tests.test_p3_review_jobs import (  # noqa: F401
    W,
    _enqueue,
    _job,
    temp_storage,
    world,
)


def test_the_running_job_says_which_page_the_reader_is_on(world, monkeypatch):  # noqa: F811
    _run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    seen = []

    def reading(*args, **kwargs):
        for number in (1, 2, 3):
            job_progress.page(number, 3)
            seen.append(_job(job_id)["progress_label"])

    monkeypatch.setattr(submittal_review, "ensure_facts_extracted", reading)
    assert review_jobs.run(job_id, W) == "done"
    assert seen == [f"reading the datasheet, page {n} of 3" for n in (1, 2, 3)]
    # the step index is the step's, not the page's
    assert _job(job_id)["progress_label"] == "done"


def test_the_reader_reports_every_page_in_order_an_empty_one_too():
    calls = []
    with job_progress.reporting(lambda done, total: calls.append((done, total))):
        datasheet_ai.read_pages({3: "c", 1: "a", 2: ""}, "off")
    assert calls == [(1, 3), (2, 3), (3, 3)]


def test_outside_a_job_nothing_is_reported_and_a_failing_line_is_ignored():
    job_progress.page(1, 1)  # no callback: a no-op

    def broken(done, total):
        raise RuntimeError("the progress store is gone")

    with job_progress.reporting(broken):
        out = datasheet_ai.read_pages({1: "a", 2: "b"}, "off")
    assert sorted(out["reasons"]) == [1, 2]  # the reading went on to the last page


def test_a_progress_line_never_commits_the_readers_unfinished_writes(world):  # noqa: F811
    _run_id, job_id = _enqueue(world)
    conn = db.connect()
    conn.execute("UPDATE jobs SET progress_label = 'mid-write' WHERE id = ?", (job_id,))
    assert conn.in_transaction
    review_jobs._page(conn, job_id, 2, 5)
    conn.rollback()
    assert _job(job_id)["progress_label"] == "queued"
    review_jobs._page(conn, job_id, 2, 5)
    assert _job(job_id)["progress_label"] == "reading the datasheet, page 2 of 5"
