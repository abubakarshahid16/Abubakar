"""Preparing a technical query's evidence runs as a JOB with progress, not inside the web request (reviewer's R6).

It reads each attachment page with the local model and searches every readable contract (dense + rerank): minutes of work that also
needs the one local model. So the request only queues the job and returns at once; one job runs at a time on its own thread; it WAITS
while a review is running (one big local model at a time) and says so in its progress label; the screen polls the query and shows
"N of M". The job runs with the permissions the person had when they asked (their readable documents are stored with the job), and a job
that was running when the server stopped is marked failed, never silently lost.

The shared `jobs` table is bound to a library document and to the review worker's claim and heartbeat rules, so this feature keeps its own
small table (`query_evidence_jobs`) instead of adding a stage to that worker.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid

from . import technical_queries
from .db import connect

log = logging.getLogger(__name__)

TABLE = "query_evidence_jobs"
WAITING_WORDS = (
    "waiting for a running review to finish (the local model runs one job at a time)"
)
INTERRUPTED_WORDS = (
    "the server stopped while this was running; prepare the evidence again"
)

#: False in tests, which run a job by hand (`run_job`) instead of on the thread.
AUTO_START = True

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def create_table(conn) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} (id TEXT PRIMARY KEY, query_id TEXT NOT NULL, state TEXT NOT NULL, "
        "progress_done INTEGER NOT NULL DEFAULT 0, progress_total INTEGER NOT NULL DEFAULT 0, label TEXT, error TEXT, "
        "caller_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )


def enqueue(
    query_id: str, allowed_document_ids, user_id, is_admin: bool, unrestricted: bool
) -> str:
    """Queue the preparation; one active job per query (the same one is returned while it is queued or running)."""
    with connect() as conn:
        create_table(conn)
        active = conn.execute(
            f"SELECT id FROM {TABLE} WHERE query_id=? AND state IN ('queued','running') ORDER BY created_at LIMIT 1",
            (query_id,),
        ).fetchone()
        if active:
            return active["id"]
        job_id, at = str(uuid.uuid4()), technical_queries.now()
        caller = {
            "allowed": sorted(allowed_document_ids),
            "user_id": user_id,
            "is_admin": bool(is_admin),
            "unrestricted": bool(unrestricted),
        }
        conn.execute(
            f"INSERT INTO {TABLE}(id,query_id,state,label,caller_json,created_at,updated_at) VALUES (?,?,'queued','queued',?,?,?)",
            (job_id, query_id, json.dumps(caller), at, at),
        )
    _wake.set()
    if AUTO_START:
        start()
    return job_id


def latest(conn, query_id: str) -> dict | None:
    """The newest job of the query, or None. Reads only: a GET never creates the table (it is made at start, by `ensure_schema`)."""
    if (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)
        ).fetchone()
        is None
    ):
        return None
    row = conn.execute(
        f"SELECT id,state,progress_done,progress_total,label,error,created_at,updated_at FROM {TABLE} WHERE query_id=? "
        "ORDER BY created_at DESC LIMIT 1",
        (query_id,),
    ).fetchone()
    return dict(row) if row else None


def _set(job_id: str, **fields) -> None:
    sets = ",".join(f"{k}=?" for k in fields) + ",updated_at=?"
    with connect() as conn:
        conn.execute(
            f"UPDATE {TABLE} SET {sets} WHERE id=?",
            (*fields.values(), technical_queries.now(), job_id),
        )


def _review_running() -> bool:
    try:
        from . import ingest

        return bool(ingest.get_worker().in_review())
    except Exception as exc:  # noqa: BLE001 - when the worker cannot be asked, go ahead; logged, never a stopped job
        log.debug("technical query job: review state not read (%s)", type(exc).__name__)
        return False


def run_job(job_id: str, *, wait_for_review: bool = True) -> None:
    """Do one job to its end (state done or failed). Used by the thread and by tests."""
    with connect() as conn:
        create_table(conn)
        row = conn.execute(
            f"SELECT query_id,caller_json FROM {TABLE} WHERE id=?", (job_id,)
        ).fetchone()
    if row is None:
        return
    caller = json.loads(row["caller_json"])
    while wait_for_review and _review_running() and not _stop.is_set():
        _set(job_id, state="queued", label=WAITING_WORDS)
        _stop.wait(5)
    _set(job_id, state="running", label="starting")

    def progress(done: int, total: int, label: str) -> None:
        _set(job_id, progress_done=done, progress_total=total, label=label)

    try:
        technical_queries.prepare_evidence(
            row["query_id"],
            frozenset(caller["allowed"]),
            caller["user_id"],
            caller["is_admin"],
            caller["unrestricted"],
            caller["user_id"],
            progress=progress,
        )
    except (
        ValueError
    ) as exc:  # a plain reason the engineer can act on (state, no question)
        _set(job_id, state="failed", error=str(exc), label="stopped")
        return
    except Exception as exc:  # noqa: BLE001 - logged by type; the job says it failed, never a hung "running"
        log.warning("technical query job: failed (%s)", type(exc).__name__)
        _set(
            job_id,
            state="failed",
            error="the evidence could not be prepared; try again",
            label="stopped",
        )
        return
    _set(job_id, state="done", label="done")


def _loop() -> None:
    while not _stop.is_set():
        with connect() as conn:
            create_table(conn)
            nxt = conn.execute(
                f"SELECT id FROM {TABLE} WHERE state='queued' ORDER BY created_at LIMIT 1"
            ).fetchone()
        if nxt is None:
            _wake.wait(30)
            _wake.clear()
            continue
        run_job(nxt["id"])


def start() -> None:
    """Start the one job thread (idempotent). Only while the feature is switched on."""
    global _thread
    if not technical_queries.enabled():
        return
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, daemon=True, name="technical-query-evidence"
        )
        _thread.start()


def stop() -> None:
    global _thread
    _stop.set()
    _wake.set()
    with _lock:
        thread, _thread = _thread, None
    if thread is not None:
        thread.join(timeout=2)


def recover_interrupted() -> int:
    """At server start: a job left `running` by a stopped server is marked failed (and said so); queued jobs are picked up again."""
    with connect() as conn:
        create_table(conn)
        changed = conn.execute(
            f"UPDATE {TABLE} SET state='failed',error=?,label='stopped',updated_at=? WHERE state='running'",
            (INTERRUPTED_WORDS, technical_queries.now()),
        ).rowcount
    return int(changed or 0)
