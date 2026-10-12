"""Claim, retry, poison and priority on the EXISTING tables (issue #177).

NOT A QUEUE PRODUCT. The queue is still `jobs` (background stages) and
`documents.status` (ingestion), drained by the one `IngestionWorker`. This
module holds only the vocabulary and the few rules both paths share, so the
retry arithmetic and the state names cannot drift between them (CLAUDE.md
rule 8: one rule, one home).

WHAT WAS MISSING, measured by the #168 audit (commit 46bd1f7):

1. No atomic claim. Both paths picked work with a plain SELECT, so two workers
   polling one database were both handed the same job and both ran it.
   `test_job_claiming_race.py` reproduced it deterministically. A claim is now
   ONE conditional UPDATE whose effect is read back (`RETURNING` - bundled
   SQLite is 3.49, and RETURNING has existed since 3.35): a worker that did
   not change the row did not get the job, whatever it read beforehand.
2. No retry. `jobs.retries` existed and nothing read it. A failed stage is now
   retried up to `settings.job_max_retries` times with doubling backoff, then
   POISONED with its last error kept - never silently dropped.
3. No priority. Work was strictly oldest-first, so an engineer's upload waited
   behind a watched-folder backfill of hundreds of historical files.
"""

from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from .config import settings

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
#: Failed, and scheduled to run again at `next_attempt_at`.
RETRYING = "retrying"
#: Failed `job_max_retries + 1` times. Nothing picks it up again on its own;
#: the last error stays on the row for an operator to read. Distinct from the
#: pre-#177 'failed', which is left exactly as an earlier build wrote it - a
#: historical failure is not reinterpreted as retryable or as poisoned.
POISONED = "poisoned"
#: B11: withdrawn before it ran. Terminal; nothing claims it.
CANCELLED = "cancelled"
#: States a person may still cancel. A RUNNING job is not among them: the
#: work is already writing rows, and stopping it half way would leave a
#: partial result labelled as nothing. Refused, and said so.
CANCELLABLE = (QUEUED, RETRYING)

#: WHERE PRIORITY COMES FROM. Higher runs first; ties run oldest-first.
#:
#: 0 is BACKFILL and is also what every row written before #177 reads as (the
#: column's DEFAULT). That is the honest reading of a historical row: nobody
#: marked it urgent, so it claims no urgency.
PRIORITY_BACKFILL = 0
#: A person is waiting on this: a file uploaded through the UI, a standard an
#: administrator pressed Extract on.
PRIORITY_INTERACTIVE = 10

#: A claim not refreshed for this long belongs to a worker that is gone and
#: may be taken by another. The holder refreshes it on every pass of the
#: document loop and every embedding batch (`IngestionWorker._touch_claim`),
#: so a live worker's claim never ages this far unless one step - a single
#: recognition round - runs longer than this. Same margin, and the same
#: reasoning, as `standards.STALE_EXTRACTION_MINUTES`.
CLAIM_STALE_SECONDS = 15 * 60

#: Random, not the host name or the pid: a worker identity must never become
#: host fingerprinting material if it is ever surfaced (status-honesty-audit
#: rows 15 and 30).
_PROCESS_TOKEN = uuid.uuid4().hex[:8]


def worker_id() -> str:
    """The default claimant: this process, this thread.

    PER THREAD, so a caller that never passes an identity is still protected
    from a second thread in the same process - which is what a second worker
    looks like when both run inside one server.
    """
    return f"w-{_PROCESS_TOKEN}-{threading.get_ident()}"


def now_iso(offset_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
            ).isoformat(timespec="seconds").replace("+00:00", "Z")


def stale_cutoff() -> str:
    return now_iso(-CLAIM_STALE_SECONDS)


def backoff_seconds(retries_so_far: int) -> float:
    """Delay before the next attempt: base, 2x base, 4x base, ..."""
    return float(settings.job_retry_base_seconds) * (2 ** max(0, retries_so_far))


def fail(conn: sqlite3.Connection, job_id: str, *, code: str, message: str) -> str:
    """Record a failed attempt on `job_id`: schedule a retry, or poison it.

    Runs inside the caller's transaction. Returns the new state. The error is
    written on BOTH outcomes - a retry that later succeeds clears it, a poison
    keeps it for good.
    """
    row = conn.execute("SELECT retries FROM jobs WHERE id = ?", (job_id,)).fetchone()
    retries = (row["retries"] if row is not None else 0) or 0
    if retries < settings.job_max_retries:
        conn.execute(
            "UPDATE jobs SET state = ?, retries = ?, next_attempt_at = ?,"
            " error_code = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (RETRYING, retries + 1, now_iso(backoff_seconds(retries)),
             code, message, now_iso(), job_id))
        return RETRYING
    conn.execute(
        "UPDATE jobs SET state = ?, next_attempt_at = NULL,"
        " error_code = ?, error_message = ?, updated_at = ? WHERE id = ?",
        (POISONED, code, message, now_iso(), job_id))
    audit(conn, "job.poisoned", job_id, detail=f"error={code}")
    return POISONED


@contextmanager
def immediate(conn: sqlite3.Connection):
    """A write transaction that takes SQLite's write lock at BEGIN (B11).

    CHECK-THEN-INSERT IS ONLY ATOMIC UNDER THIS. A deferred transaction reads
    under a shared lock, so two requests can both see "no pending job" and both
    insert one. BEGIN IMMEDIATE makes the second wait until the first commits,
    and it then reads the first one's job."""
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    conn.commit()


def audit(conn: sqlite3.Connection, action: str, job_id: str, *,
          actor_user_id: str | None = None, detail: str | None = None) -> None:
    """B11: a job lifecycle event in `audit_events`, IN THE CALLER'S
    TRANSACTION - never swallowed, so a transition cannot happen unrecorded.
    Ids and states only."""
    conn.execute(
        """INSERT INTO audit_events
               (at, actor_user_id, actor_username, action,
                resource_type, resource_id, outcome, detail)
           VALUES (?, ?, ?, ?, 'job', ?, 'ok', ?)""",
        (now_iso(), actor_user_id, (actor_user_id or "system")[:200],
         action, job_id, detail))


def cancel(job_id: str, *, actor_user_id: str | None) -> tuple[bool, str | None]:
    """Cancel a job that has not started. Returns (cancelled NOW, state):
    (True, 'cancelled'), or (False, its current state) when it could not be -
    including one already cancelled, which this call did not do - or
    (False, None) when there is no such job.

    ONE CONDITIONAL UPDATE, like a claim: a worker that claims the job in the
    same instant wins or loses cleanly - never both run and cancelled."""
    from .db import connect
    conn = connect()
    with conn:
        row = conn.execute(
            f"""UPDATE jobs SET state = ?, next_attempt_at = NULL, updated_at = ?
                WHERE id = ? AND state IN ({','.join('?' * len(CANCELLABLE))})
                RETURNING id""",
            (CANCELLED, now_iso(), job_id, *CANCELLABLE)).fetchone()
        if row is not None:
            audit(conn, "job.cancelled", job_id, actor_user_id=actor_user_id)
            return True, CANCELLED
        current = conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return False, (current["state"] if current else None)


_JOB_COLUMNS = ("id, document_id, stage, state, priority, retries, error_code,"
                " pages_total, pages_done, next_attempt_at, started_at, updated_at,"
                " created_by, code_version, config_version, review_run_id,"
                " progress_done, progress_total, progress_label, cancel_requested")


def list_jobs(*, allowed_document_ids: frozenset[str], document_id: str | None = None,
              state: str | None = None, limit: int = 100) -> list[dict]:
    """B11: jobs on documents the caller may read. Scope first, filters after:
    a filter can only narrow it (CLAUDE.md rule 5)."""
    from .db import connect
    ids = sorted(allowed_document_ids if document_id is None
                 else allowed_document_ids & {document_id})
    if not ids:
        return []
    where = [f"document_id IN ({','.join('?' * len(ids))})"]
    args: list = list(ids)
    if state:
        where.append("state = ?")
        args.append(state)
    rows = connect().execute(
        f"SELECT {_JOB_COLUMNS} FROM jobs WHERE {' AND '.join(where)}"
        " ORDER BY updated_at DESC LIMIT ?", (*args, limit)).fetchall()
    return [dict(r) for r in rows]


def get_job(job_id: str, *, allowed_document_ids: frozenset[str]) -> dict | None:
    """One job, or None when it does not exist OR its document is not readable -
    the same answer, so a job id cannot be used to learn a document exists."""
    from .db import connect
    row = connect().execute(
        f"SELECT {_JOB_COLUMNS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None or row["document_id"] not in allowed_document_ids:
        return None
    return dict(row)


def under_limit_sql(stage_param: str = ":stage") -> str:
    """B11: the concurrency bound, as a clause for a claiming UPDATE. Counts
    only LIVE running claims, so a row left 'running' by a dead process does
    not block the queue until the startup sweep reclaims it."""
    return (f"(SELECT COUNT(*) FROM jobs WHERE stage = {stage_param}"
            " AND state = 'running' AND claimed_at >= :stale) < :limit")


def queue_counts(pending_documents_sql: str, pending_args: tuple) -> dict:
    """Operator counts for the admin metrics block. Corpus-wide by design.

    `queued` and `running` join the two queues honestly: an ingestion job row
    sits in 'running' from upload to completion whether or not anything is
    working on it, so for DOCUMENTS the claim - not the job row - says which
    are being worked on. Background stage jobs say it with their own state.
    `retrying` and `poisoned` are job states on both paths.
    """
    from .db import connect
    conn = connect()
    stale = stale_cutoff()
    docs = conn.execute(
        f"""SELECT
              SUM(CASE WHEN claimed_by IS NOT NULL AND claimed_at >= ? THEN 1 ELSE 0 END) AS held,
              COUNT(*) AS pending
            FROM documents WHERE {pending_documents_sql}""",
        (stale, *pending_args)).fetchone()
    by_state = {
        r["state"]: r["n"] for r in conn.execute(
            "SELECT state, COUNT(*) AS n FROM jobs"
            " WHERE stage NOT IN ('extract', 'chunk') OR state IN (?, ?)"
            " GROUP BY state", (RETRYING, POISONED))
    }
    held = docs["held"] or 0
    return {
        "queued": (docs["pending"] or 0) - held + by_state.get(QUEUED, 0),
        "running": held + by_state.get(RUNNING, 0),
        "retrying": by_state.get(RETRYING, 0),
        "poisoned": by_state.get(POISONED, 0),
    }
