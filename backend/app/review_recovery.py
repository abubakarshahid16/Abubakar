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
    """How many jobs were recovered or cancelled. See `review_jobs.recover_stale`."""
    conn = connect()
    mine = f"w-{job_queue._PROCESS_TOKEN}-%"
    foreign = (
        " OR claimed_by IS NULL OR claimed_by NOT LIKE :mine" if at_startup else ""
    )
    with conn:
        jobs = conn.execute(
            "SELECT id, review_run_id, cancel_requested FROM jobs WHERE stage = :stage"
            f" AND state = 'running' AND (claimed_at IS NULL OR claimed_at < :cutoff{foreign})",
            {"stage": stage, "cutoff": job_queue.stale_cutoff(), "mine": mine},
        ).fetchall()
        for job in jobs:
            if job["cancel_requested"]:
                _cancel(conn, job, stage)
                continue
            conn.execute(
                "UPDATE jobs SET state = 'queued', claimed_by = NULL, claimed_at = NULL,"
                " updated_at = ? WHERE id = ?",
                (_now(), job["id"]),
            )
            conn.execute(
                "UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
                (_now(), job["review_run_id"]),
            )
            job_queue.audit(conn, "job.recovered", job["id"], detail=f"stage={stage}")
    return len(jobs)


def _cancel(conn, job, stage: str) -> None:
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
    conn.execute(
        "UPDATE jobs SET state = ?, claimed_by = NULL, claimed_at = NULL, updated_at = ?"
        " WHERE id = ?",
        (job_queue.CANCELLED, _now(), job["id"]),
    )
    job_queue.audit(
        conn,
        "job.cancelled",
        job["id"],
        detail=f"cancel found after a restart ({stage})",
    )
