# ruff: noqa: F811 - pytest fixtures imported by name
"""The review's overall progress: four named steps, step 2's page line names step 2, step 3 counts requirements.

Owner report on a live review: the bar went from step 1 at 73% back to step 2 at 36% and called step 2 "reading the
document"; in step 3 the bar vanished. Invented documents only; no model runs.
"""

from __future__ import annotations

from app import comparison, db, job_progress, review_jobs, review_progress
from tests.test_p3_review_jobs import (  # noqa: F401 - fixtures
    W,
    _enqueue,
    _job,
    temp_storage,
    world,
)


def _row(label, done=None, **kw):
    return {"progress_label": label, "progress_done": done, "id": "j", **kw}


def test_the_step_comes_from_the_jobs_own_step_index_and_label():
    assert review_progress.detail(_row("reading the document", 0))["step"] == 1
    assert (
        review_progress.detail(_row("selecting the applicable standards", 1))["step"]
        == 2
    )
    assert (
        review_progress.detail(_row("comparing requirements with the document", 2))[
            "step"
        ]
        == 3
    )
    assert (
        review_progress.detail(_row("finishing: AI comments and wording", 2))["step"]
        == 4
    )
    assert review_progress.detail(_row("checking clause 3 of 9", 2))["step"] == 4
    assert (
        review_progress.detail(_row("", None))["step"] is None
    )  # unknown: null, never a guess


def test_step_3_counts_finished_requirements_and_says_nothing_outside_it():
    d = review_progress.detail(_row("comparing requirements, 1241 of 5062", 2))
    assert (d["requirements_done"], d["requirements_total"], d["step"]) == (
        1240,
        5062,
        3,
    )
    assert d["waiting_on"] and d["stall_amber_seconds"] > 900
    other = review_progress.detail(_row("reading the document, page 3 of 9", 0))
    assert other["requirements_done"] is None and other["requirements_total"] is None


def test_the_page_line_of_step_2_names_step_2_not_reading(world):
    _run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    conn = db.connect()
    review_jobs._step(conn, job_id, 1)
    review_jobs._page(conn, job_id, 3, 11)
    label = _job(job_id)["progress_label"]
    assert label == "selecting the applicable standards, page 3 of 11"
    d = review_progress.detail(_row(label, 1))
    assert (d["step"], d["pages_done"], d["pages_total"]) == (2, 2, 11)
    review_jobs._step(conn, job_id, 0)
    review_jobs._page(conn, job_id, 3, 11)
    assert _job(job_id)["progress_label"] == "reading the document, page 3 of 11"


def test_counting_yields_every_item_unchanged_and_in_order_with_or_without_a_callback():
    items = [{"a": 1}, {"b": 2}, {"c": 3}]
    assert list(job_progress.counting(items)) == items
    seen = []
    with job_progress.reporting_requirements(lambda n, t: seen.append((n, t))):
        assert list(job_progress.counting(items)) == items
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_a_failing_progress_callback_never_changes_what_is_compared():
    def boom(n, t):
        raise RuntimeError("disk full")

    items = list(range(5))
    with job_progress.reporting_requirements(boom):
        assert list(job_progress.counting(items)) == items


def test_the_requirement_line_is_written_at_most_once_a_second_but_always_first_and_last(
    world,
):
    _run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    conn = db.connect()
    review_jobs._REQUIREMENT_WRITTEN.pop(job_id, None)
    review_jobs._requirement(conn, job_id, 1, 5)
    assert _job(job_id)["progress_label"] == "comparing requirements, 1 of 5"
    for n in (2, 3, 4):
        review_jobs._requirement(conn, job_id, n, 5)
    assert (
        _job(job_id)["progress_label"] == "comparing requirements, 1 of 5"
    )  # throttled
    review_jobs._requirement(conn, job_id, 5, 5)
    assert _job(job_id)["progress_label"] == "comparing requirements, 5 of 5"


def test_the_comparison_loop_reports_each_requirement_to_the_job(world, monkeypatch):
    _run_id, job_id = _enqueue(world)
    review_jobs.claim_next(W)
    calls = []
    monkeypatch.setattr(
        review_jobs,
        "_requirement",
        lambda conn, j, n, t, hb=None: calls.append((j, n, t)),
    )
    assert review_jobs.run(job_id, W) == "done"
    assert calls and calls[0][:2] == (job_id, 1) and calls[-1][1] == calls[-1][2]
    assert (
        comparison.job_progress is job_progress
    )  # the loop goes through the one wrapper
