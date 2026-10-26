"""Order 231: a restart no longer blocks the review queue for 15 minutes.

A review cancelled or crashed in a process that is gone kept its claim for
`CLAIM_STALE_SECONDS`, so the next review sat at "Waiting to start". At STARTUP every
claim held by another process is dead and is recovered at once; a job whose cancel was
already requested is cancelled, never queued to run again; a live worker's fresh claim is
untouched; the sweep in the drain loop stays stale-only. Invented documents only.
"""

# ruff: noqa: F811 - pytest fixtures imported from test_p3_review_jobs are re-declared as arguments
from __future__ import annotations

from app import db, job_queue, review_jobs
from tests.test_p3_review_jobs import (  # noqa: F401
    W,
    _enqueue,
    _job,
    _run_row,
    temp_storage,
    world,
)


def _claimed_by(world, who: str = W):
    run_id, job_id = _enqueue(world)
    assert review_jobs.claim_next(who) == job_id
    return run_id, job_id


def test_at_startup_a_fresh_claim_of_a_dead_process_is_recovered_at_once(world):
    run_id, job_id = _claimed_by(world)
    assert (
        review_jobs.recover_stale() == 0
    )  # the drain loop's sweep: a fresh claim is a live worker's
    assert _job(job_id)["state"] == "running"
    assert review_jobs.recover_stale(at_startup=True) == 1
    assert _job(job_id)["state"] == "queued" and _run_row(run_id)["status"] == "queued"
    assert review_jobs.claim_next("w-new") == job_id


def test_at_startup_a_claim_of_this_process_is_left_alone(world):
    _run_id, job_id = _claimed_by(world, who=job_queue.worker_id())
    assert review_jobs.recover_stale(at_startup=True) == 0
    assert _job(job_id)["state"] == "running"


def test_a_cancelled_review_found_after_a_restart_is_cancelled_not_queued_again(world):
    run_id, job_id = _claimed_by(world)
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
    assert review_jobs.recover_stale(at_startup=True) == 1
    assert _job(job_id)["state"] == job_queue.CANCELLED
    assert _run_row(run_id)["status"] == "cancelled"
    assert review_jobs.claim_next("w-new") is None  # it never runs again


def test_a_cancelled_review_with_a_stale_claim_is_cancelled_by_the_drain_loops_sweep_too(
    world,
):
    run_id, job_id = _claimed_by(world)
    with db.connect() as conn:
        conn.execute(
            "UPDATE jobs SET cancel_requested = 1, claimed_at = '2000-01-01T00:00:00Z' WHERE id = ?",
            (job_id,),
        )
    assert review_jobs.recover_stale() == 1
    assert (
        _job(job_id)["state"] == job_queue.CANCELLED
        and _run_row(run_id)["status"] == "cancelled"
    )


def test_the_next_review_starts_at_once_after_the_restart(world):
    """The owner's case: a cancelled review holds a claim; the next review must not wait."""
    _first_run, first = _claimed_by(world)
    with db.connect() as conn:
        conn.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (first,))
        conn.execute(
            "UPDATE review_runs SET status = 'cancelled' WHERE id = ?", (_first_run,)
        )
    review_jobs.recover_stale(at_startup=True)
    second_run, second = _enqueue(world)
    assert review_jobs.claim_next("w-new") == second
    assert _run_row(second_run)["status"] == "running"
