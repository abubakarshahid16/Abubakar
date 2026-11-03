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

import contextlib
import functools
import json
import logging
import time
import uuid
from pathlib import Path

from . import (
    access,
    ai_call_ledger,
    ai_review_pass,
    claude_auto_approve,
    claude_spend_report,
    job_progress,
    job_queue,
    local_engine_bar,
    nothing_read,
    provenance,
    reread_for_standards,
    review_progress,
    submittal_fill,
    word_pages,
)
from .config import config_version, settings
from .db import connect

STAGE = "review_run"
#: The steps, in order. Progress is "step N of 3", named - never a percentage
#: of something nobody measured.
STEPS = ("reading the datasheet", "selecting the applicable standards",
         "comparing requirements with the datasheet")
ACTIVE_RUN = ("queued", "running")

#: The word a progress line uses for the submittal: its CONFIRMED kind, else
#: "document" (a suggested kind is a guess, rule 4). the live review: a procedure's
#: review said "reading the datasheet".
_KIND_WORDS = {
    "datasheet": "datasheet",
    "procedure": "procedure",
    "specification": "specification",
    "drawing": "drawing",
    "transmittal": "transmittal",
    "contract": "contract",
    "feed": "FEED",
}
#: (noun, unit) when nothing is known: neutral, and a PDF's unit.
NEUTRAL_WORDS = ("document", "page")


def document_words(document_id: str) -> tuple[str, str]:
    """(noun, unit) for the progress lines of a review of `document_id`. The
    unit is "part" for a Word file read in parts (`pagination = 'flow'`), else "page".
    WORD_PAGE_MARKERS_ENABLED: a Word file shows pages, "part" only with no page marks."""
    from . import doc_router, document_kind

    stored = document_kind.stored_kind(document_id)
    confirmed = stored is not None and stored[1] == doc_router.STATE_CONFIRMED
    noun = _KIND_WORDS.get(stored[0] or "", "document") if confirmed else "document"
    row = (
        connect()
        .execute("SELECT pagination FROM documents WHERE id = ?", (document_id,))
        .fetchone()
    )
    unit = "part" if row is not None and row["pagination"] == "flow" else "page"
    if settings.word_page_markers_enabled:
        unit = word_pages.unit(document_id)
    return noun, unit


def _job_words(job_id: str) -> tuple[str, str]:
    """`document_words` of the job's submittal; neutral when the job is gone."""
    sql = "SELECT document_id FROM jobs WHERE id = ?"
    row = connect().execute(sql, (job_id,)).fetchone()
    return document_words(row["document_id"]) if row else NEUTRAL_WORDS


def step_label(index: int, words: tuple[str, str] = NEUTRAL_WORDS) -> str:
    """STEPS[index] with the submittal's own noun in place of "datasheet"."""
    return STEPS[index].replace("datasheet", words[0])


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
             requested_by, review_code_version(), config_version(), run_id, len(STEPS)))
        job_queue.audit(conn, "job.queued", job_id, actor_user_id=requested_by,
                        detail=f"stage={STAGE} run={run_id}")
    claude_auto_approve.on_review_start(run_id)  # #1584
    return run_id, job_id


#: Roadmap R5 (#763): the modules whose code decides a review's result. Their
#: source, plus the data files in `app/reference/` they read, IS the review
#: code version: stamped on every review job, and compared by the readiness
#: check, so "nothing changed since the last run" is never said after the
#: review code changed (it was, live, on 10 Oct 2026).
REVIEW_CODE_MODULES = (
    "comparison", "applicability", "datasheets", "datasheet_checks", "match_rules",
    "crs_mapping", "service_scope", "subject_scope", "scope_ledger", "claims", "numparse",
    "page_ledger", "table_gate", "requirement_quality", "submittal_review",
)
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"


def review_code_version() -> str:
    """`review@<12 hex>` over the review modules' source and every
    `reference/*.json` data file. Derived, never typed (see `provenance`);
    recomputed each call, so a changed data file is seen without a restart."""
    import hashlib
    digest = hashlib.sha256(provenance.code_version(*REVIEW_CODE_MODULES).encode())
    for path in sorted(REFERENCE_DIR.glob("*.json")):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    return f"review@{digest.hexdigest()[:12]}"


def last_run_versions(review_run_id: str) -> dict | None:
    """The code and config versions stamped on a run's job; None when the run
    has no job row (a run started before jobs existed, or by another route)."""
    row = connect().execute(
        "SELECT code_version, config_version FROM jobs WHERE review_run_id = ?"
        " ORDER BY started_at DESC LIMIT 1", (review_run_id,)).fetchone()
    return dict(row) if row else None


def job_for_run(review_run_id: str) -> dict | None:
    row = connect().execute(
        "SELECT id, state, progress_done, progress_total, progress_label, cancel_requested"
        " FROM jobs WHERE review_run_id = ? ORDER BY started_at DESC LIMIT 1",
        (review_run_id,)).fetchone()
    job = dict(row) if row else None
    block = review_progress.for_job(job) if job else None  # #1494, switch off: None
    return {**job, "progress_detail": block} if block else job


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


def _step(conn, job_id: str, index: int, heartbeat=None, words=NEUTRAL_WORDS) -> None:
    """Record progress and honour a cancellation - between steps, never inside one."""
    if heartbeat is not None:
        heartbeat()
    with conn:
        row = conn.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row and row["cancel_requested"]:
            raise _Cancelled()
        conn.execute(
            "UPDATE jobs SET progress_done = ?, progress_label = ?, claimed_at = ?,"
            " updated_at = ? WHERE id = ?",
            (index, step_label(index, words), _now(), _now(), job_id),
        )


def _page(
    conn, job_id: str, done: int, total: int, heartbeat=None, words=NEUTRAL_WORDS
) -> None:
    """Order 95 piece 3b: the page the reader is on, inside step 1's label -
    "reading the procedure, page 3 of 11" ("part" for a Word file, `words`).
    Progress only: the step index and
    the job's claim are left as they are.

    SKIPPED INSIDE AN OPEN TRANSACTION. The reader shares this thread's
    connection; committing a progress line there would commit the reader's
    unfinished writes with it. A skipped line costs one stale label. The worker
    heartbeat is NOT skipped: the page was read, so the worker is moving."""
    if heartbeat is not None:
        heartbeat()
    if conn.in_transaction:
        return
    label = f"{step_label(0, words)}, {words[1]} {done} of {total}"
    with conn:
        sql = "UPDATE jobs SET progress_label = ?, updated_at = ? WHERE id = ?"
        conn.execute(sql, (label, _now(), job_id))


def _clause(conn, job_id: str, number: int, total: int, heartbeat=None) -> None:
    """#1494: the clause the AI clause review is on - "checking clause 12 of 60".
    Same rules as `_page`: progress only, skipped inside an open transaction, the
    worker heartbeat is not skipped. Numbers only, never clause text."""
    if heartbeat is not None:
        heartbeat()
    if number == 1:
        job_progress.CLAUSE_STARTED[job_id] = time.time()
    if conn.in_transaction:
        return
    with conn:
        sql = "UPDATE jobs SET progress_label = ?, updated_at = ? WHERE id = ?"
        conn.execute(sql, (f"checking clause {number} of {total}", _now(), job_id))


def _checks_reporting(conn, job_id: str, heartbeat, run_id, scope, missing) -> None:
    """`_checks` with the clause review's "checking clause N of M" going to the job (#1494)."""
    try:
        with job_progress.reporting_clauses(
            lambda n, t: _clause(conn, job_id, n, t, heartbeat)
        ):
            _checks(run_id, scope, missing)
    finally:
        job_progress.CLAUSE_STARTED.pop(job_id, None)


def _reporting_pages(conn, job_id: str, heartbeat=None, words=NEUTRAL_WORDS):
    """The reader's page reports go to this job's label for the block (3b)."""
    return job_progress.reporting(
        lambda done, total: _page(conn, job_id, done, total, heartbeat, words)
    )


@contextlib.contextmanager
def _phase(
    conn, job_id: str, index: int | None, heartbeat, timings: dict, name: str | None
):
    """A phase of the run: a beat of the worker's heartbeat at its start, the
    step recorded when it has an `index`, timed in the trace when it has a
    `name`, and its reader page reports are also heartbeats. Its lines name the
    submittal's own kind and unit (the live review: never "datasheet" on a
    procedure, never "page" on a Word file)."""
    from . import review_trace

    words = _job_words(job_id)
    if index is not None:
        _step(conn, job_id, index, heartbeat, words)
    elif heartbeat is not None:
        heartbeat()
    timed = review_trace.timed(timings, name) if name else contextlib.nullcontext()
    with timed, _reporting_pages(conn, job_id, heartbeat, words):
        yield


#: The run's outcome is stored before the AI comments, numbers and wording are
#: written (order 236): the run reads as running, and says so, until the end.
FINISHING = "finishing: AI comments and wording"


def _label(conn, job_id: str, label: str) -> None:
    with conn:
        conn.execute(
            "UPDATE jobs SET progress_label = ?, updated_at = ? WHERE id = ?",
            (label, _now(), job_id),
        )


def _record_check_failure(run_id: str, column: str, name: str, exc: BaseException) -> None:
    """Store "<check> could not be checked: <ErrorName>" on the run. The error's
    TYPE only: no text from the failure, which could carry document text."""
    from . import absence
    status = absence.check_failed_status(name, f"it failed ({type(exc).__name__})")
    assert column in ("ai_check_status", "web_check_status")
    try:
        if column == "ai_check_status":
            from . import clause_review

            return clause_review.write_ai_status(run_id, status)
        conn = connect()
        with conn:
            conn.execute(f"UPDATE review_runs SET {column} = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(status), _now(), run_id))
    except Exception:  # noqa: BLE001 - recording must not fail the review either
        import logging
        logging.getLogger(__name__).warning("could not record %s failure", column)


def settle_drafts(run_id: str) -> None:
    """Order 224.1: exact repeats among the AI check's drafts are marked.
    Never fails the review."""
    try:
        from . import ai_check_drafts

        ai_check_drafts.settle(run_id)
    except Exception as exc:  # noqa: BLE001 - drafts are optional; the review stands
        import logging

        logging.getLogger(__name__).warning(
            "AI check drafts not settled: %s", type(exc).__name__
        )


def _ai_check(run_id: str, scope: frozenset[str], missing: list[str]) -> None:
    """Owner order 2d: the AI engineering check, AFTER the comparison decided
    the code, only with its flag on. Drafts only; a failure here (budget,
    Claude refused, a bad answer) never fails the review - it is logged by
    kind, never with text."""
    from . import ai_engineering_check
    if not settings.review_ai_check_enabled:
        return
    try:
        result = ai_engineering_check.run_check(run_id, allowed_document_ids=scope, cited=missing)
        # #501: the datasheet-only opinion of the cloud model, when its own
        # engine setting asks for one. Its own declaration: the submittal only.
        ai_engineering_check.run_datasheet_opinion(run_id, allowed_document_ids=scope, cited=missing)
        # `run_check` already stores `ai_check_status` on the run itself - the
        # reviewer's view of this. This is only the operator's log line, by
        # kind and never with text, same as the except below.
        if result.get("ran") and not result.get("complete", True):
            import logging
            logging.getLogger(__name__).info(
                "AI engineering check incomplete for run %s: %s calls, reason=%s",
                run_id, result.get("calls_made"), result.get("reason"))
        settle_drafts(run_id)
    except Exception as exc:  # noqa: BLE001 - drafts are optional; the review stands
        import logging
        logging.getLogger(__name__).warning("AI engineering check skipped: %s", type(exc).__name__)
        # #633: AND IT SAYS SO ON THE RUN. The review stands, but a reviewer must
        # be able to tell "ran, nothing to raise" from "could not be checked".
        _record_check_failure(run_id, "ai_check_status", "AI engineering check", exc)


def _checks(run_id: str, scope: frozenset[str], missing: list[str]) -> None:
    """The review's optional checks, after the comparison. None fails the review."""
    from . import ai_senior_review, clause_review, spec_kit, transmittal_kit

    _ai_check(run_id, scope, missing)
    _web_check(run_id, scope, missing)
    clause_review.for_review(run_id, scope)
    spec_kit.for_review(run_id, scope)  # #1479
    transmittal_kit.for_review(run_id, scope)  # #1482
    ai_senior_review.for_review(run_id, scope)  # step 3 of #805, off by default


def _web_check(run_id: str, scope: frozenset[str], missing: list[str]) -> None:
    """Owner order 2d-2: the public web standards check, AFTER the comparison
    decided the code, only with its flag on. Drafts only (kind D); a failure
    here (no transport, a fetch error, an unverifiable quote) never fails
    the review - it is logged by kind, never with text or the identifier
    that failed."""
    from . import web_standards
    if not settings.review_web_standards_enabled:
        return
    try:
        from . import market_transport
        web_standards.run_check(
            run_id, allowed_document_ids=scope, missing_identifiers=missing,
            fetch_search=market_transport.transport(),
            fetch_text=lambda url, timeout: market_transport.fetch_text(url, timeout=timeout))
        settle_drafts(run_id)
    except Exception as exc:  # noqa: BLE001 - drafts are optional; the review stands
        import logging
        logging.getLogger(__name__).warning("web standards check skipped: %s", type(exc).__name__)
        _record_check_failure(run_id, "web_check_status", "Web standards check", exc)


def _review_scope(job):
    """A Claude-lane run never loads the local engine, its spend lines name the run, and its spend goes in its record."""
    barred = local_engine_bar.barring_local_engine(job)

    @functools.wraps(job)
    def wrapper(job_id, *args, **kwargs):
        from . import claude_spend

        sql = "SELECT review_run_id FROM jobs WHERE id = ?"
        row = connect().execute(sql, (job_id,)).fetchone()
        run_id = row["review_run_id"] if row else None
        try:
            with claude_spend.for_run(run_id):
                return barred(job_id, *args, **kwargs)
        finally:
            claude_spend_report.record_run(run_id)

    return wrapper


def _audit_ended(job_id: str) -> None:
    """#1525: the audit of a review that ended without finishing. Never raises."""
    from . import review_audit

    try:
        sql = "SELECT review_run_id, created_by FROM jobs WHERE id = ?"
        job = connect().execute(sql, (job_id,)).fetchone()
        scope = access.AccessScope(
            user_id=job["created_by"], allowed_document_ids=_scope_of(job["created_by"])
        )
        review_audit.write(job["review_run_id"], scope)
    except Exception:  # an audit never breaks or changes a review
        logging.getLogger(__name__).warning("review audit not written", exc_info=True)


def _audit_when_it_ended(job):
    """A failed or cancelled review gets its audit too; a retry is not the end of a run."""

    @functools.wraps(job)
    def wrapper(job_id, *args, **kwargs):
        state = job(job_id, *args, **kwargs)
        ended = state in (job_queue.POISONED, job_queue.CANCELLED)
        if ended and settings.review_audit_report_enabled:
            _audit_ended(job_id)
        return state

    return wrapper


@ai_call_ledger.recorded  # #1525: only with REVIEW_AUDIT_REPORT_ENABLED on
@_audit_when_it_ended  # #1525, the same switch
@_review_scope  # the bar on the local engine; ledger lines carry the run's id
def run(job_id: str, worker_id: str, heartbeat=None) -> str:
    """Run one claimed review job to its end. Returns the job's final state.

    `heartbeat`, optional: forwarded to `applicability.select()`. This job
    runs on the SAME single worker thread as document ingestion
    (`ingest.IngestionWorker._drain_review_jobs`) - see that module for why
    the two share one thread. Without this, the worker's own heartbeat only
    ticks at its outer loop boundary, so a slow, uncached scope-reasoning
    pass (hundreds of standards, no cached answer yet) reads on the
    Documents page as the worker having no heartbeat / "not moving", when it
    is in fact still working through this one job.
    """
    from . import applicability, comparison, errors, review_audit, review_trace
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

        timings: dict = {}    # #791 part 1: when each phase ran, for the stored trace
        with _phase(conn, job_id, 0, heartbeat, timings, "read"):
            nothing_read.read_phase(submittal, scope, run_id)
        with _phase(conn, job_id, 1, heartbeat, timings, "standards"):
            submittal_fill.for_review(submittal)
            selection = applicability.select(submittal, allowed_document_ids=scope,
                                             review_run_id=run_id, persist=True, heartbeat=heartbeat)
            from . import company_standard_confirm

            held = company_standard_confirm.held_readable(scope)  # #620
            reread_for_standards.for_review(submittal, scope, run_id, timings)
        with _phase(conn, job_id, 2, heartbeat, timings, "compare"):
            comparison.run_comparison(
                run_id, allowed_document_ids=scope,
                reference_coverage=selection.get("reference_coverage"),
                missing_references=[m["identifier"] for m in selection["missing_references"]])
            company_standard_confirm.record_on_run(run_id, held)
        _label(conn, job_id, FINISHING)
        with _phase(conn, job_id, None, heartbeat, timings, "checks"):
            missing = [m["identifier"] for m in selection["missing_references"]]
            _checks_reporting(conn, job_id, heartbeat, run_id, scope, missing)
        requester = access.AccessScope(user_id=job["created_by"], allowed_document_ids=scope)
        from .main import number_crs_rows, word_crs_rows
        with _phase(conn, job_id, None, heartbeat, timings, None):
            number_crs_rows(run_id, requester)  # R15 (#779)
            word_crs_rows(run_id, requester)
            ai_review_pass.run_for_job(run_id, requester)  # lane 6, off by default
        # #791: the run's stored trace (reads only, never fails the run), then REVIEW_DEBUG prints it.
        review_trace.store(run_id, requester, timings)
        review_trace.emit(run_id, requester)
        review_audit.write(run_id, requester, timings)  # #1525
    except nothing_read.StoredFileAbsent as exc:  # #1495
        return nothing_read.fail_run(job_id, run_id, exc)
    except _Cancelled:
        with conn:
            from . import review as review_mod
            conn.execute("DELETE FROM review_findings WHERE review_run_id = ?"
                         f" AND {review_mod.UNDECIDED_SQL}", (run_id,))
            conn.execute("UPDATE review_runs SET status = 'cancelled', outcome_json = ?,"
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
                # #633: FINDINGS WRITTEN BEFORE THE FAILURE ARE PARTIAL, and the
                # run says so. They were committed before the datasheet checks
                # and the outcome, so a later failure left findings with no
                # code and nothing to say the set was incomplete.
                written = conn.execute(
                    "SELECT COUNT(*) FROM review_findings WHERE review_run_id = ?",
                    (run_id,)).fetchone()[0]
                conn.execute("UPDATE review_runs SET status = 'failed', outcome_json = ?,"
                             " updated_at = ? WHERE id = ?",
                             (json.dumps({"error": safe["message"],
                                          **({"partial": True, "partial_findings": written}
                                             if written else {})}), _now(), run_id))
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


def recover_stale(*, at_startup: bool = False) -> int:
    """A review job left `running` by a dead process goes back to the queue, and its
    run with it; one whose cancel was already requested is CANCELLED, never queued to
    run again (order 231). Only stale claims - a live worker keeps its claim fresh at
    every step - and, `at_startup` (the server's boot, before any worker of this
    process exists), every claim held by another process: a restart means every old
    claim is dead, so a cancelled or crashed review no longer blocks the queue for
    `CLAIM_STALE_SECONDS`. The sweep inside the drain loop stays stale-only."""
    from . import review_recovery

    return review_recovery.recover(STAGE, at_startup=at_startup)
