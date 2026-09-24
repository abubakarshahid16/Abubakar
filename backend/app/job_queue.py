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
    return POISONED


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
