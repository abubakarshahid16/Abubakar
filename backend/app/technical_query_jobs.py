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
import sqlite3
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
#: The rules that propose a query's question: 2 = the mail's introduction, greetings and pointers to the attachment are never the question;
#: the attached form's own question field is (lead-4, 26 Nov 2026). A query prepared under older rules with no confirmed question is
#: prepared again by "Prepare evidence for all".
#: 3 = a cover line whatever its punctuation, boilerplate and links ask nothing, the form's question SECTION, why nothing was proposed
#: (lead-4's live walk on update 13): the queries re-proposed under 2 are proposed again.
#: 4 = every page of an attachment is read (up to 60, was 5) and the papers of a LATER mail of the thread too (builder H, update 15;
#: lead-4's live walk, 26 Nov 2026: queries prepared before them kept the old proposals): those prepared under 3 are proposed again.
#: 5 = a lead-in line ("... the following two points:") is an unnumbered lead, never an item; a request that points back ("... on the
#: above understanding") brings the statement it points to; an answer-choice cell is never a question (#2009, the owner's 15:18 fault;
#: lead-5, 27 Nov 2026: the 34 live queries must get it, not only new ones): those prepared under 4 are proposed again at the next start.
QUESTION_RULES = 5

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
    columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({TABLE})")}
    # when the preparation itself began (waiting in the queue is not counted): the measured minutes per query come from it
    if "started_at" not in columns:
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN started_at TEXT")
    # the question rules a preparation ran under (QUESTION_RULES); older ones are proposed again (an engineer's confirmed question never)
    if "question_rules" not in columns:
        conn.execute(f"ALTER TABLE {TABLE} ADD COLUMN question_rules INTEGER")


def enqueue(
    query_id: str,
    allowed_document_ids,
    user_id,
    is_admin: bool,
    unrestricted: bool,
    *,
    start_thread: bool = True,
) -> str:
    """Queue the preparation; one active job per query (the same one is returned while it is queued or running). `start_thread=False`
    (the automatic preparation after an import) only queues it: the app's one job thread, started with the app, takes it in turn."""
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
            f"INSERT INTO {TABLE}(id,query_id,state,label,caller_json,created_at,updated_at,question_rules) "
            "VALUES (?,?,'queued','queued',?,?,?,?)",
            (job_id, query_id, json.dumps(caller), at, at, QUESTION_RULES),
        )
    _wake.set()
    if AUTO_START and start_thread:
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
        "ORDER BY created_at DESC, rowid DESC LIMIT 1",  # two jobs of one second (a refresh right after a preparation): the later one
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


#: How long a preparation waits for its query's papers to be read, and what it says meanwhile.
READING_WAIT = 30 * 60
READING_WORDS = "waiting for the query's attachments to be read"


def _attachments_reading(query_id: str) -> bool:
    """True while a paper this query took in (not a signature picture) is still being read by the ingest worker."""
    from . import states

    settled = sorted(
        states.TERMINAL_STATES | {states.PARTIALLY_SEARCHABLE}
    )  # the ingest worker's own "finished" set
    with connect() as conn:
        return (
            conn.execute(
                "SELECT 1 FROM query_attachments a JOIN query_messages m ON m.id=a.message_id JOIN documents d ON d.id=a.document_id "
                f"WHERE m.query_id=? AND d.status NOT IN ({','.join('?' * len(settled))}) LIMIT 1",
                (query_id, *settled),
            ).fetchone()
            is not None
        )


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
    _set(job_id, state="running", label="starting", started_at=technical_queries.now())

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
    # the proposed reply follows at once, written by the LOCAL model, so the query opens ready (owner, 26 Nov 2026 21:36); a draft that
    # cannot be written leaves its reason on the query and the job still ends done (the evidence is there)
    _set(job_id, label="writing the draft with the local model")
    from . import technical_query_auto

    try:
        technical_query_auto.write_draft(row["query_id"], frozenset(caller["allowed"]), caller["user_id"], caller["is_admin"],
                                         caller["unrestricted"])  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - logged by type; the evidence stays, the draft can be generated by hand
        log.warning("technical query job: draft not written (%s)", type(exc).__name__)
    _set(job_id, state="done", label="done")


def next_ready(conn) -> str | None:
    """The oldest queued job whose query's papers are read, or which has waited READING_WAIT for them; a job still waiting for its papers
    is passed over (it says so) and taken again on a later turn, so it never holds back the queries behind it (recheck of update 12, R5)."""
    from datetime import UTC, datetime, timedelta

    create_table(conn)
    cutoff = (datetime.now(UTC) - timedelta(seconds=READING_WAIT)).strftime(
        "%Y-%m-%dT%H:%M:%S"
    )
    for row in conn.execute(
        f"SELECT id, query_id, created_at FROM {TABLE} WHERE state='queued' ORDER BY created_at"
    ).fetchall():
        if (row["created_at"] or "") <= cutoff or not _attachments_reading(
            row["query_id"]
        ):
            return row["id"]
        _set(row["id"], label=READING_WORDS)
    return None


def _loop() -> None:
    while not _stop.is_set():
        with connect() as conn:
            nxt = next_ready(conn)
        if nxt is None:
            _wake.wait(
                15
            )  # nothing ready: a new job or a paper read in a moment wakes the turn again
            _wake.clear()
            continue
        run_job(nxt)


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


#: The states a query can be prepared in (as `technical_queries.prepare_evidence` accepts).
PREPARABLE = ("received", "triage", "drafting", "changes_requested")


def unprepared(conn) -> list[str]:
    """The queries in a state that can be prepared with no preparation queued, running or done (a failed one counts as unprepared); a
    preparation done under older question rules counts as not done when no engineer has confirmed the question (re-proposed)."""
    create_table(conn)
    out = [
        r[0]
        for r in conn.execute(
            f"SELECT q.id FROM technical_queries q WHERE q.status IN ({','.join('?' * len(PREPARABLE))}) AND NOT EXISTS "
            f"(SELECT 1 FROM {TABLE} j WHERE j.query_id=q.id AND (j.state IN ('queued','running') OR (j.state='done' AND "
            "(COALESCE(j.question_rules,1) >= ? OR COALESCE(q.confirmed_question,'') != '')))) ORDER BY q.received_at",
            (*PREPARABLE, QUESTION_RULES),
        )
    ]
    # AWAITING REVIEW on a MODEL's reply prepared under older question rules (lead-5, 27 Nov 2026: rules 5 must reach the 34 live
    # queries, and 20 of them await review): proposed again too, with the draft redo's guards - no engineer decision, no confirmed
    # question, the latest draft written by a model (never an engineer's own typed reply). The start-up backlog sends it back to drafting.
    seen = set(out)
    try:
        awaiting = conn.execute(
            f"SELECT q.id FROM technical_queries q WHERE q.status='awaiting_review' AND COALESCE(q.confirmed_question,'')='' "
            "AND NOT EXISTS (SELECT 1 FROM query_decisions x WHERE x.query_id=q.id) "
            "AND COALESCE((SELECT d.model FROM query_drafts d WHERE d.query_id=q.id ORDER BY d.version DESC LIMIT 1),'') != '' "
            f"AND NOT EXISTS (SELECT 1 FROM {TABLE} j WHERE j.query_id=q.id AND (j.state IN ('queued','running') OR (j.state='done' AND "
            "COALESCE(j.question_rules,1) >= ?))) "
            f"AND EXISTS (SELECT 1 FROM {TABLE} j WHERE j.query_id=q.id AND j.state='done') ORDER BY q.received_at",
            (QUESTION_RULES,),
        ).fetchall()
    except sqlite3.OperationalError:  # the drafts or decisions table not made yet (a fresh database): nothing awaits review
        awaiting = []
    for r in awaiting:
        if r[0] not in seen:
            out.append(r[0])
            seen.add(r[0])
    return out


def minutes_each(conn) -> int | None:
    """Whole minutes one preparation took, the median of the last 10 finished ones (from start to end, waiting not counted), or None."""
    create_table(conn)
    rows = conn.execute(
        f"SELECT (julianday(updated_at) - julianday(started_at)) * 1440 FROM {TABLE} "
        "WHERE state='done' AND started_at IS NOT NULL ORDER BY updated_at DESC LIMIT 10"
    ).fetchall()
    spans = sorted(r[0] for r in rows if r[0] is not None and r[0] >= 0)
    return max(1, round(spans[len(spans) // 2])) if spans else None


def all_plan(conn) -> dict:
    """What "Prepare evidence for all unprepared queries" would do, and how far a started round has got (counts only)."""
    create_table(conn)
    waiting = conn.execute(
        f"SELECT COUNT(*) FROM {TABLE} WHERE state IN ('queued','running')"
    ).fetchone()[0]
    from . import technical_query_auto

    return {
        "unprepared": len(technical_query_auto.backlog(conn)),
        "minutes_each": minutes_each(conn),
        "waiting_or_running": waiting,
    }


def queue_all(
    allowed_document_ids, user_id, is_admin: bool, unrestricted: bool
) -> dict:
    """Queue every unprepared query (one at a time, by the one evidence thread), with the pressing administrator's read scope."""
    from . import technical_query_auto

    with connect() as conn:
        ids = technical_query_auto.backlog(
            conn
        )  # never prepared, prepared with no draft and no reason why, or an older system draft
        stale = set(technical_query_auto.stale_system_drafts(conn))
        for (
            query_id
        ) in stale:  # back to drafting, so the job may prepare and draft again
            conn.execute(
                "UPDATE technical_queries SET status='drafting' WHERE id=? AND status='awaiting_review'",
                (query_id,),
            )
    for query_id in ids:
        enqueue(query_id, allowed_document_ids, user_id, is_admin, unrestricted)
    with connect() as conn:
        return {**all_plan(conn), "queued_now": len(ids)}
