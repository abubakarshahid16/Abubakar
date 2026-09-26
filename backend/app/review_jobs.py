"""P3: a review runs as a background job on the B11 queue, not inside the request.

THE SAME QUEUE, NOT A SECOND ONE. A review is a `jobs` row with stage
`review_run`, claimed by the one worker with the same conditional UPDATE,
retried and poisoned by `job_queue.fail`, audited by `job_queue.audit` and
bounded by `settings.job_max_running`. What this module adds is only what a
review needs that an extraction does not:

  * the run it belongs to (`jobs.review_run_id`), created in the SAME write
    lock as the job, so there is never a queued review without its job or
    two active reviews of one submittal;
  * the REQUESTER'S SCOPE. The worker has no caller, but a review must see
    exactly what the engineer who asked may read - never "every document".
    The job records who asked; the worker rebuilds that person's scope from
    the grant tables when it runs (unrestricted only when auth is disabled);
  * progress in three named steps, and cooperative cancellation between them.
    A cancelled review deletes the findings it had written, so a half-run
    never reads as a result.
"""

from __future__ import annotations

import json
import uuid

from . import access, job_queue, provenance
from .config import config_version, settings
from .db import connect

STAGE = "review_run"
#: The steps, in order. Progress is "step N of 3", named - never a percentage
#: of something nobody measured.
STEPS = ("reading the datasheet", "selecting the applicable standards",
         "comparing requirements with the datasheet")
ACTIVE_RUN = ("queued", "running")


class ReviewAlreadyActive(RuntimeError):
    """A review of this submittal is queued or running; args[0] is its run id."""


def _now() -> str:
    return job_queue.now_iso()


def enqueue(submittal_document_id: str, *, allowed_document_ids: frozenset[str],
            requested_by: str | None) -> tuple[str, str]:
    """Create the run and its job together. Returns (run_id, job_id).

    Raises ReviewAlreadyActive when a review of this submittal is queued or
    running, and ValueError when the caller may not read the submittal."""
    from . import submittal_review
    submittal_review.ensure_schema()
    if submittal_document_id not in allowed_document_ids:
        raise ValueError("no submittal with that id")
    conn = connect()
    run_id, job_id, now = str(uuid.uuid4()), f"job_{uuid.uuid4().hex[:12]}", _now()
    with job_queue.immediate(conn):
        active = conn.execute(
            f"SELECT id FROM review_runs WHERE submittal_document_id = ?"
            f" AND status IN ({','.join('?' * len(ACTIVE_RUN))}) LIMIT 1",
            (submittal_document_id, *ACTIVE_RUN)).fetchone()
        if active is not None:
            raise ReviewAlreadyActive(active["id"])
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, started_by,"
            " started_at, created_at, updated_at) VALUES (?,?,'queued',?,?,?,?)",
            (run_id, submittal_document_id, requested_by, now, now, now))
        conn.execute(
            """INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at,
                                 priority, created_by, code_version, config_version,
                                 review_run_id, progress_done, progress_total, progress_label)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?, 'queued')""",
            (job_id, submittal_document_id, STAGE, now, now, job_queue.PRIORITY_INTERACTIVE,
             requested_by, provenance.code_version("comparison", "applicability", "datasheets"),
             config_version(), run_id, len(STEPS)))
        job_queue.audit(conn, "job.queued", job_id, actor_user_id=requested_by,
                        detail=f"stage={STAGE} run={run_id}")
    return run_id, job_id


def job_for_run(review_run_id: str) -> dict | None:
    row = connect().execute(
        "SELECT id, state, progress_done, progress_total, progress_label, cancel_requested"
        " FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
        (review_run_id,)).fetchone()
    return dict(row) if row else None


_CLAIMABLE = ("(state = 'queued' OR (state = 'retrying'"
              " AND next_attempt_at IS NOT NULL AND next_attempt_at <= :now))")


def claim_next(worker_id: str) -> str | None:
    """Claim the next review job (one conditional UPDATE). Returns its id."""
    now = _now()
    conn = connect()
    with conn:
        row = conn.execute(
            f"""UPDATE jobs SET state = 'running', claimed_by = :me, claimed_at = :now,
                       updated_at = :now
                WHERE id = (SELECT id FROM jobs WHERE stage = :stage AND {_CLAIMABLE}
                            ORDER BY priority DESC, started_at LIMIT 1)
                  AND {_CLAIMABLE} AND {job_queue.under_limit_sql()}
                RETURNING id, review_run_id""",
            {"me": worker_id, "now": now, "stage": STAGE, "stale": job_queue.stale_cutoff(),
             "limit": settings.job_max_running}).fetchone()
        if row is None:
            return None
        conn.execute("UPDATE review_runs SET status = 'running', updated_at = ? WHERE id = ?",
                     (now, row["review_run_id"]))
    return row["id"]


class _Cancelled(Exception):
    pass


def _scope_of(user_id: str | None) -> frozenset[str]:
    """The requester's scope, rebuilt now from the grant tables - the same
    decision `access.current_scope` makes for a request: with sign-in disabled
    every caller is unrestricted, so the review is too."""
    if settings.auth_mode == access.AUTH_DISABLED:
        return access.unrestricted_scope().allowed_document_ids
    if user_id is None:
        return frozenset()
    return access.scope_for_user(user_id).allowed_document_ids


def _step(conn, job_id: str, index: int) -> None:
    """Record progress and honour a cancellation - between steps, never inside one."""
    with conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row and row["cancel_requested"]:
            raise _Cancelled()
        conn.execute("UPDATE jobs SET progress_done = ?, progress_label = ?, claimed_at = ?,"
                     " updated_at = ? WHERE id = ?",
                     (index, STEPS[index], _now(), _now(), job_id))


def run(job_id: str, worker_id: str) -> str:
    """Run one claimed review job to its end. Returns the job's final state."""
    from . import applicability, comparison, errors, submittal_review
    conn = connect()
    job = conn.execute("SELECT * FROM jobs WHERE id = ? AND state = 'running' AND claimed_by = ?",
                       (job_id, worker_id)).fetchone()
    if job is None:
        return "not_claimed"
    run_id, submittal = job["review_run_id"], job["document_id"]
    scope = _scope_of(job["created_by"])
    try:
        if submittal not in scope:
            raise PermissionError("the requester can no longer read this submittal")
        _step(conn, job_id, 0)
        submittal_review.ensure_facts_extracted(submittal, scope, review_run_id=run_id)
        _step(conn, job_id, 1)
        selection = applicability.select(submittal, allowed_document_ids=scope,
                                         review_run_id=run_id, persist=True)
        _step(conn, job_id, 2)
        comparison.run_comparison(
            run_id, allowed_document_ids=scope,
            reference_coverage=selection.get("reference_coverage"),
            missing_references=[m["identifier"] for m in selection["missing_references"]])
    except _Cancelled:
        with conn:
            conn.execute("DELETE FROM review_findings WHERE review_run_id = ?"
                         " AND confirmed_by IS NULL", (run_id,))
            conn.execute("UPDATE review_runs SET status = 'cancelled', refusal_reason = ?,"
                         " updated_at = ? WHERE id = ?",
                         (json.dumps({"error": "cancelled by an engineer before it finished"}),
                          _now(), run_id))
            conn.execute("UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
                         (job_queue.CANCELLED, _now(), job_id))
            job_queue.audit(conn, "job.cancelled", job_id, detail=f"run={run_id} while running")
        return job_queue.CANCELLED
    except Exception as exc:  # noqa: BLE001 - a failed review must not kill the worker
        safe = errors.record_failure(exc, document_id=submittal, stage=STAGE)
        with conn:
            state = job_queue.fail(conn, job_id, code=type(exc).__name__, message=safe["message"])
            if state == job_queue.POISONED:
                conn.execute("UPDATE review_runs SET status = 'failed', refusal_reason = ?,"
                             " updated_at = ? WHERE id = ?",
                             (json.dumps({"error": safe["message"]}), _now(), run_id))
            else:
                conn.execute("UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
                             (_now(), run_id))
        return state
    with conn:
        conn.execute("UPDATE jobs SET state = 'done', progress_done = ?, progress_label = 'done',"
                     " error_code = NULL, error_message = NULL, next_attempt_at = NULL,"
                     " updated_at = ? WHERE id = ?", (len(STEPS), _now(), job_id))
        job_queue.audit(conn, "job.done", job_id, detail=f"stage={STAGE} run={run_id}")
    return "done"


def cancel(job_id: str, *, actor_user_id: str | None) -> tuple[bool, str | None]:
    """Cancel a review job. Queued or retrying: now. Running: requested, and
    honoured at the next step. Returns (accepted, state)."""
    done, state = job_queue.cancel(job_id, actor_user_id=actor_user_id)
    conn = connect()
    if done:
        with conn:
            conn.execute("UPDATE review_runs SET status = 'cancelled', updated_at = ? WHERE id ="
                         " (SELECT review_run_id FROM jobs WHERE id = ?)", (_now(), job_id))
        return True, state
    if state == job_queue.RUNNING:
        with conn:
            conn.execute("UPDATE jobs SET cancel_requested = 1, updated_at = ? WHERE id = ?",
                         (_now(), job_id))
            job_queue.audit(conn, "job.cancel_requested", job_id, actor_user_id=actor_user_id)
        return True, state
    return False, state


def recover_stale() -> int:
    """Startup: a review job left `running` by a dead process goes back to the
    queue, and its run with it. Only stale claims - a live worker keeps its
    claim fresh at every step."""
    conn = connect()
    with conn:
        rows = conn.execute(
            "UPDATE jobs SET state = 'queued', claimed_by = NULL, claimed_at = NULL,"
            " updated_at = ? WHERE stage = ? AND state = 'running'"
            " AND (claimed_at IS NULL OR claimed_at < ?) RETURNING id, review_run_id",
            (_now(), STAGE, job_queue.stale_cutoff())).fetchall()
        for r in rows:
            conn.execute("UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
                         (_now(), r["review_run_id"]))
            job_queue.audit(conn, "job.recovered", r["id"], detail=f"stage={STAGE}")
    return len(rows)
