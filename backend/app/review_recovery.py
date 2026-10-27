"""Put back, or cancel, the review jobs a dead process left `running` (order 231).

The sweep behind `review_jobs.recover_stale`. A job whose claim is stale, or at the server's
startup held by another process, is queued again with its run; one whose cancel was already
requested is CANCELLED with its run and its undecided findings, never queued to run again.
"""

from __future__ import annotations

import json

from . import job_queue
from . import review as review_mod
from .db import connect
from .job_queue import now_iso as _now


def recover(stage: str, *, at_startup: bool = False) -> int:
    """How many jobs were recovered or cancelled. See `review_jobs.recover_stale`.

    Each job is taken by ONE conditional UPDATE that repeats the "dead" test, like a
    claim: a worker that refreshed its claim between the look and the update is never put
    back in the queue (it would run twice)."""
    conn = connect()
    foreign = (
        " OR claimed_by IS NULL OR claimed_by NOT LIKE :mine" if at_startup else ""
    )
    dead = f"(claimed_at IS NULL OR claimed_at < :cutoff{foreign})"
    args = {
        "stage": stage,
        "cutoff": job_queue.stale_cutoff(),
        "mine": f"w-{job_queue._PROCESS_TOKEN}-%",
    }
    done = 0
    with conn:
        ids = conn.execute(
            f"SELECT id FROM jobs WHERE stage = :stage AND state = 'running' AND {dead}",
            args,
        ).fetchall()
        for found in ids:
            taken = conn.execute(
                "UPDATE jobs SET state = CASE cancel_requested WHEN 1 THEN :cancelled ELSE 'queued' END,"
                " claimed_by = NULL, claimed_at = NULL, updated_at = :now"
                f" WHERE id = :id AND stage = :stage AND state = 'running' AND {dead}"
                " RETURNING id, review_run_id, cancel_requested",
                {
                    **args,
                    "id": found["id"],
                    "now": _now(),
                    "cancelled": job_queue.CANCELLED,
                },
            ).fetchone()
            if taken is None:  # its worker refreshed the claim in between: a live job
                continue
            done += 1
            if taken["cancel_requested"]:
                _cancel(conn, taken, stage)
                continue
            conn.execute(
                "UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
                (_now(), taken["review_run_id"]),
            )
            job_queue.audit(conn, "job.recovered", taken["id"], detail=f"stage={stage}")
    return done


def _cancel(conn, job, stage: str) -> None:
    """The run of a job already marked cancelled ends like a cancel a live worker honours:
    its undecided findings are removed and its outcome says it was cancelled."""
    conn.execute(
        "DELETE FROM review_findings WHERE review_run_id = ?"
        f" AND {review_mod.UNDECIDED_SQL}",
        (job["review_run_id"],),
    )
    conn.execute(
        "UPDATE review_runs SET status = 'cancelled', outcome_json = ?, updated_at = ?"
        " WHERE id = ?",
        (
            json.dumps({"error": "cancelled by an engineer before it finished"}),
            _now(),
            job["review_run_id"],
        ),
    )
    job_queue.audit(
        conn,
        "job.cancelled",
        job["id"],
        detail=f"cancel found after a restart ({stage})",
    )
