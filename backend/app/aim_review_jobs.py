"""The general review's job (order 14, piece B): queued by the ONE Review button, run by the review worker.

`enqueue` makes the `review_runs` row, the `jobs` row (stage `aim_review`) and the `aim_runs` row in ONE transaction, with the
engine choice, the list shown before the start and the consent (the caller's `in_transaction`). ONE review of a paper at a time,
across all three stages (`review_jobs.ReviewAlreadyActive`).

`run` reads the paper as the old jobs do (nothing read: the run fails loudly, nothing is sent), then hands the method
(`app.aim_review.run`) ONLY the rule books on the list the screen showed (`review_shown.shown_ids`, minus the paper itself, inside
the requester's scope). A run with no stored list gets no rule book at all. The method makes every call inside
`claude_spend.for_run` and `claude_approved.reviewing`; this module adds the run's spend record (`review_jobs._review_scope`).
Cancel is honoured between steps and between judge batches. A failed run is NEVER retried by itself (a retry would pay again):
its run row says "failed" in plain words. No document text is logged or stored here: ids, counts and fixed words only.

With the old engine on (`aim_review_gate.old_engine_on()`): nothing is queued, claimed or recovered here.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid

from . import (
    aim_review,
    aim_review_completeness,
    aim_review_gate,
    aim_review_store,
    claude_auto_approve,
    job_queue,
    review_jobs,
    review_shown,
)
from .config import config_version
from .db import connect

log = logging.getLogger(__name__)

STAGE = "aim_review"
STEPS = ("read the paper", "name the paper", "checklist", "judge", "counts")
ACTIVE_RUN = review_jobs.ACTIVE_RUN
#: The run row's words when a run failed (the class of the fault is kept in the job; never a document's text).
FAILED_WORDS = "the general review stopped on an error and was not retried (a retry would pay again); start it again"
CANCELLED_WORDS = "cancelled by an engineer before it finished"
NO_FILE_WORDS = "the paper's stored file could not be found, so nothing was read and nothing was sent"
SWITCHED_OFF_WORDS = (
    "the general review is switched off on this install (REVIEW_OLD_ENGINE_ENABLED)"
)


class GeneralReviewOff(RuntimeError):
    """The old engine is on: the general review queues nothing."""


class _Cancelled(Exception):
    pass


def _now() -> str:
    return job_queue.now_iso()


# ---------------------------------------------------------------- enqueue, claim, recover


def enqueue(
    paper_id: str,
    *,
    allowed_document_ids: frozenset[str],
    requested_by: str | None,
    in_transaction=None,
) -> tuple[str, str]:
    """Create the run and its job together. Returns (run_id, job_id). `in_transaction(conn, run_id)` runs inside the same
    transaction (the engine choice, the shown list, the consent). Raises `GeneralReviewOff` with the old engine on,
    `ValueError` when the caller may not read the paper, `review_jobs.ReviewAlreadyActive` when any review of it is active."""
    if not aim_review_gate.general_on():
        raise GeneralReviewOff(SWITCHED_OFF_WORDS)
    from . import review_engine, submittal_review

    submittal_review.ensure_schema()
    aim_review_store.ensure_schema()
    if paper_id not in allowed_document_ids:
        raise ValueError("no submittal with that id")
    conn = connect()
    run_id, now = str(uuid.uuid4()), _now()
    job_id = review_engine.new_job_id(in_transaction is not None)
    with job_queue.immediate(conn):
        active = conn.execute(
            f"SELECT id FROM review_runs WHERE submittal_document_id = ?"
            f" AND status IN ({','.join('?' * len(ACTIVE_RUN))}) LIMIT 1",
            (paper_id, *ACTIVE_RUN),
        ).fetchone()
        if active is not None:
            raise review_jobs.ReviewAlreadyActive(active["id"])
        conn.execute(
            "INSERT INTO review_runs (id, submittal_document_id, status, started_by,"
            " started_at, created_at, updated_at) VALUES (?,?,'queued',?,?,?,?)",
            (run_id, paper_id, requested_by, now, now, now),
        )
        conn.execute(
            """INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at,
                                 priority, created_by, code_version, config_version,
                                 review_run_id, progress_done, progress_total, progress_label)
               VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?, 0, ?, 'queued')""",
            (
                job_id,
                paper_id,
                STAGE,
                now,
                now,
                job_queue.PRIORITY_INTERACTIVE,
                requested_by,
                review_jobs.review_code_version(),
                config_version(),
                run_id,
                len(STEPS),
            ),
        )
        aim_review_store.start_run(conn, run_id, paper_id, now)
        if in_transaction is not None:
            in_transaction(conn, run_id)
        job_queue.audit(
            conn,
            "job.queued",
            job_id,
            actor_user_id=requested_by,
            detail=f"stage={STAGE} run={run_id}",
        )
    claude_auto_approve.on_review_start(
        run_id
    )  # #1584 route 2: the paper joins the approved list, unless blocked or a contract
    return run_id, job_id


def claim_next(worker_id: str) -> str | None:
    """Claim the next general review job (one conditional UPDATE). None with the old engine on or nothing queued."""
    if not aim_review_gate.general_on():
        return None
    from .config import settings

    now = _now()
    conn = connect()
    with conn:
        row = conn.execute(
            f"""UPDATE jobs SET state = 'running', claimed_by = :me, claimed_at = :now, updated_at = :now
                WHERE id = (SELECT id FROM jobs WHERE stage = :stage AND {review_jobs._CLAIMABLE}
                            ORDER BY priority DESC, started_at LIMIT 1)
                  AND {review_jobs._CLAIMABLE} AND {job_queue.under_limit_sql()}
                RETURNING id, review_run_id""",
            {
                "me": worker_id,
                "now": now,
                "stage": STAGE,
                "stale": job_queue.stale_cutoff(),
                "limit": settings.job_max_running,
            },
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            "UPDATE review_runs SET status = 'running', updated_at = ? WHERE id = ?",
            (now, row["review_run_id"]),
        )
    return row["id"]


def recover_stale(*, at_startup: bool = False) -> int:
    """A job left `running` by a dead process goes back to the queue (it starts again from the beginning; the saved checklist is
    reused, so a restart pays for the judging again, never for the checklist). A job already marked cancelled ends cancelled, and
    its general run says so. Nothing at all with the old engine on."""
    if not aim_review_gate.general_on():
        return 0
    from . import review_recovery

    done = review_recovery.recover(STAGE, at_startup=at_startup)
    if done:
        conn = connect()
        aim_review_store.ensure_schema(conn)
        for row in conn.execute(
            f"SELECT r.id FROM review_runs r JOIN {aim_review_store.RUNS} a ON a.run_id = r.id"
            " WHERE r.status = 'cancelled' AND a.status IN ('queued', 'running')"
        ).fetchall():
            _store_end(conn, row["id"], "cancelled", CANCELLED_WORDS)
    return done


# ---------------------------------------------------------------- the run


def _cancel_requested(conn, job_id: str) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    return bool(row and row["cancel_requested"])


def _progress(conn, job_id: str, step: int, heartbeat=None) -> None:
    """Record the step and honour a cancellation: between steps, never inside one."""
    if heartbeat is not None:
        heartbeat()
    if _cancel_requested(conn, job_id):
        raise _Cancelled()
    with conn:
        conn.execute(
            "UPDATE jobs SET progress_done = ?, progress_label = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
            (step, STEPS[min(step, len(STEPS) - 1)], _now(), _now(), job_id),
        )


def allowed_books(
    conn, run_id: str, paper_id: str, scope: frozenset[str]
) -> frozenset[str]:
    """The rule books the method may carry: the list the screen showed for this run, minus the paper, inside the requester's
    scope (rule 5: only narrows). No stored list: none."""
    shown = review_shown.shown_ids(conn, run_id)
    if not shown:
        return frozenset()
    return frozenset(d for d in shown if d != paper_id and d in scope)


def _store_end(
    conn, run_id: str, status: str, words: str, result: dict | None = None
) -> None:
    """The general run's row ends truthfully (failed / cancelled), keeping any lines a result already holds."""
    body = dict(result or {})
    body["status"] = status
    body["stop_reason"] = body.get("stop_reason") or words
    body.setdefault("lines", [])
    aim_review_store.finish_run(conn, run_id, body, _now())


def _result_dict(result) -> dict:
    return (
        dataclasses.asdict(result) if dataclasses.is_dataclass(result) else dict(result)
    )


def _fail(conn, job_id: str, run_id: str, paper_id: str, exc: Exception) -> str:
    from . import errors

    safe = errors.record_failure(exc, document_id=paper_id, stage=STAGE)
    with conn:
        conn.execute(
            "UPDATE jobs SET state = ?, next_attempt_at = NULL, error_code = ?, error_message = ?, updated_at = ? WHERE id = ?",
            (job_queue.POISONED, type(exc).__name__, safe["message"], _now(), job_id),
        )
        job_queue.audit(
            conn, "job.poisoned", job_id, detail=f"error={type(exc).__name__}"
        )
        conn.execute(
            "UPDATE review_runs SET status = 'failed', outcome_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps({"general_review": True, "error": FAILED_WORDS}),
                _now(),
                run_id,
            ),
        )
    try:
        _store_end(conn, run_id, "failed", FAILED_WORDS)
    except Exception as store_exc:  # noqa: BLE001 - the run row above already says failed
        log.warning("general review: run row not closed (%s)", type(store_exc).__name__)
    return job_queue.POISONED


def _cancelled(conn, job_id: str, run_id: str, result: dict | None = None) -> str:
    with conn:
        conn.execute(
            "UPDATE review_runs SET status = 'cancelled', outcome_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps({"general_review": True, "error": CANCELLED_WORDS}),
                _now(),
                run_id,
            ),
        )
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
            (job_queue.CANCELLED, _now(), job_id),
        )
        job_queue.audit(
            conn, "job.cancelled", job_id, detail=f"run={run_id} while running"
        )
    _store_end(conn, run_id, "cancelled", CANCELLED_WORDS, result)
    return job_queue.CANCELLED


def _done(conn, job_id: str, run_id: str, result: dict) -> str:
    aim_review_store.finish_run(conn, run_id, result, _now())
    aim_review_completeness.record_after_run(run_id)
    outcome = {
        "general_review": True,
        "status": result.get("status"),
        "stop_reason": result.get("stop_reason") or None,
        "points": len(result.get("lines") or []),
        # a run that stopped early (run cap, lane closed, a fault) keeps its lines and says so; it is never a finished review
        "partial": result.get("status") == "stopped",
    }
    with conn:
        conn.execute(
            "UPDATE review_runs SET status = 'completed', outcome_json = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (json.dumps(outcome), _now(), _now(), run_id),
        )
        conn.execute(
            "UPDATE jobs SET state = 'done', progress_done = ?, progress_label = 'done', error_code = NULL,"
            " error_message = NULL, next_attempt_at = NULL, updated_at = ? WHERE id = ?",
            (len(STEPS), _now(), job_id),
        )
        job_queue.audit(conn, "job.done", job_id, detail=f"stage={STAGE} run={run_id}")
    return job_queue.DONE


def _not_read(text) -> dict:
    """The run of a paper with no stored text to read (or still being read in): stopped, no line, the plain reason."""
    return {
        "status": "stopped",
        "stop_reason": text.stop,
        "lines": [],
        "books": [],
        "usd": 0.0,
        "seconds": 0.0,
    }


def _requeue_switched_off(conn, job_id: str, run_id: str) -> str:
    """The old engine was switched on while this job waited: it goes back to the queue untouched (nothing sent)."""
    with conn:
        conn.execute(
            "UPDATE jobs SET state = 'queued', claimed_by = NULL, claimed_at = NULL, updated_at = ? WHERE id = ?",
            (_now(), job_id),
        )
        conn.execute(
            "UPDATE review_runs SET status = 'queued', updated_at = ? WHERE id = ?",
            (_now(), run_id),
        )
    return job_queue.QUEUED


def _cross_document(conn, paper_id: str, scope, start: int) -> list[dict]:
    """The cross-document check by tag (`tag_cross`; code only, Questions only), inside the starter's read set. A fault of the
    check adds no line and never stops the review (logged, class only)."""
    from . import cross_doc, cross_doc_meaning, tag_cross

    out: list[dict] = []
    try:
        # lane 1 (builder H, switch CROSS_DOC_FACTS_ENABLED) replaces C's check by tag; off, C's check runs exactly as before
        lane = cross_doc if cross_doc.lane_on() else tag_cross
        out = lane.lines(conn, paper_id, frozenset(scope), start)
    except Exception as exc:  # noqa: BLE001 - the check is an addition: the review stands without it
        log.warning("cross-document check skipped: %s", type(exc).__name__)
    # lane 2 (switch CROSS_DOC_MEANING_ENABLED): questions to the engineer only
    if cross_doc_meaning.lane_on():
        try:
            n = start + len(out)
            out += cross_doc_meaning.lines(conn, paper_id, frozenset(scope), n)
        except Exception as exc:  # noqa: BLE001 - the same: an addition
            log.warning("cross-document meaning check skipped: %s", type(exc).__name__)
    return out


@review_jobs._review_scope  # the run's spend lines carry its id; its spend goes in its record
def run(job_id: str, worker_id: str, heartbeat=None, *, model=None) -> str:
    """Run one claimed general review job to its end. Returns the job's final state. `model`: tests pass the method's fake model;
    the shipped worker passes nothing (the method builds the Claude model)."""
    from . import (
        agent_review_text,
        nothing_read,
    )  # nothing_read: a stored file found absent while the paper is read

    conn = connect()
    job = conn.execute(
        "SELECT * FROM jobs WHERE id = ? AND state = 'running' AND claimed_by = ? AND stage = ?",
        (job_id, worker_id, STAGE),
    ).fetchone()
    if job is None:
        return "not_claimed"
    run_id, paper_id = job["review_run_id"], job["document_id"]
    if not aim_review_gate.general_on():
        return _requeue_switched_off(conn, job_id, run_id)
    scope = review_jobs._scope_of(job["created_by"])
    holder: dict = {}
    try:
        if paper_id not in scope:
            raise PermissionError("the requester can no longer read this paper")
        _progress(conn, job_id, 0, heartbeat)
        # THE PAPER'S STORED TEXT ONLY (rehearsal, 18 Nov): the method reads the stored pages and, for a page with no text layer,
        # its recognised text (`aim_review.paper.load_paper`). The older datasheet field reader (`agent_review_text.read_step` ->
        # `submittal_review.ensure_facts_extracted`) made 23+ Claude calls on one paper before the method began, and the method
        # uses none of its facts, so it is not run here. A paper still being read in, or with no text at all, stops with words.
        text = agent_review_text.read(conn, paper_id)
        if text.stops_run(True):
            return _done(conn, job_id, run_id, _not_read(text))
        books = allowed_books(conn, run_id, paper_id, scope)
        # #1584 route 3: the rule books the reviewer will ask rules from join the approved list just before it asks, only when the
        # paper qualifies and only inside the starter's scope (`on_agent_standards`; off: nothing). The send gate still decides.
        claude_auto_approve.on_agent_standards(paper_id, sorted(books), run_id)

        def progress(_pct: int, words: str) -> None:
            if heartbeat is not None:
                heartbeat()
            if words in STEPS:
                with conn:
                    conn.execute(
                        "UPDATE jobs SET progress_done = ?, progress_label = ?, claimed_at = ?, updated_at = ? WHERE id = ?",
                        (STEPS.index(words), words, _now(), _now(), job_id),
                    )

        result = aim_review.run(
            conn,
            run_id=run_id,
            paper_id=paper_id,
            allowed_books=books,
            store=aim_review_store.DbChecklistStore(conn),
            max_usd=aim_review_gate.max_usd(),
            progress=progress,
            cancelled=lambda: _cancel_requested(conn, job_id),
            model=model,
        )
        result.lines += _cross_document(conn, paper_id, scope, len(result.lines))
        holder["result"] = _result_dict(result)
        if _cancel_requested(conn, job_id):
            raise _Cancelled()
        _progress(conn, job_id, 4, heartbeat)
    except nothing_read.StoredFileAbsent as exc:
        state = nothing_read.fail_run(job_id, run_id, exc)
        _store_end(conn, run_id, "failed", NO_FILE_WORDS)
        return state
    except _Cancelled:
        return _cancelled(conn, job_id, run_id, holder.get("result"))
    except Exception as exc:  # noqa: BLE001 - a failed review must not kill the worker
        log.warning(
            "general review failed: %s", type(exc).__name__
        )  # the class only, never a text
        return _fail(conn, job_id, run_id, paper_id, exc)
    return _done(conn, job_id, run_id, holder["result"])
