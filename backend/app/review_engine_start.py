"""Starting a review from the ONE Review button: queue the parts the plan runs, in order (owner decision, 12 Nov 2026, #1584).

The plan is made by `review_engine.plan_for` (the one resolver). Here it is ACTED ON:
  1. the rule check is queued (`review_jobs.enqueue`), its choice stored with the plan; when the plan puts it on this computer
     the run is barred from Claude (`review_engine.barring`) for its whole length;
  2. when the plan runs the AI review too, it follows the rule check on the same worker as soon as the rule check is done
     (`follow_up`; the app runs one review of a paper at a time, so the two cannot be queued together). The follow-up is made
     under the same person's scope and checked again against the then-current approvals: a plan that no longer holds starts
     nothing and says why on the run's choice record.

Never a call, never a model load: it only queues. Words and ids only are stored.
"""

from __future__ import annotations

import logging

from . import (
    agent_review_gate,
    agent_review_jobs,
    job_queue,
    review_engine,
    review_jobs,
)
from .db import connect

log = logging.getLogger(__name__)


class StartRefused(Exception):
    """The plan refused the start; `code` and the plain sentence."""

    def __init__(self, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.code, self.sentence = code, sentence


def start(
    document_id: str,
    allowed: frozenset[str],
    requested_by: str | None,
    choice: str,
    *,
    fresh: bool = False,
    project_document_ids: tuple[str, ...] = (),
) -> tuple[str, dict]:
    """Queue the review the plan allows. Returns (run id of the first part, plan). Raises `StartRefused` (nothing queued) and
    `review_jobs.ReviewAlreadyActive`."""
    conn = connect()
    plan = review_engine.plan_for(conn, document_id, allowed, choice)
    if plan["refused"]:
        raise StartRefused(plan["refused_code"] or "REFUSED", plan["refused"])
    parts = {p["name"]: p for p in plan["parts"]}
    plan["project_document_ids"] = list(project_document_ids)
    plan["fresh"] = bool(fresh)
    then_ai = parts[review_engine.AI_REVIEW]["engine"] in (
        review_engine.ON_CLAUDE,
        review_engine.ON_LOCAL,
    )
    bar = parts[review_engine.RULE_CHECK]["engine"] != review_engine.ON_CLAUDE

    def choice_with_the_job(txn_conn, new_run_id: str) -> None:
        # In the SAME transaction as the job: a worker that claims the job finds its choice (and so its bar) already there.
        review_engine.record_in(
            txn_conn,
            new_run_id,
            plan,
            requested_by,
            then_ai=then_ai,
            bar_claude=bar,
            now=job_queue.now_iso(),
        )

    run_id, _job = review_jobs.enqueue(
        document_id,
        allowed_document_ids=allowed,
        requested_by=requested_by,
        in_transaction=choice_with_the_job,
    )
    return run_id, plan


def follow_up(job_id: str, state: str) -> str | None:
    """After a rule-check job: start the AI review its plan asked for. Returns the new run id or None. Never raises: a start that
    cannot be made is recorded on the run's choice (`followed_by`), and the rule check's result stands."""
    if state != job_queue.DONE:
        return None
    conn = connect()
    try:
        row = conn.execute(
            "SELECT review_run_id, created_by, document_id, stage FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if row is None or row["stage"] != review_jobs.STAGE:
            return None
        got = review_engine.stored(conn, row["review_run_id"])
        if not got or not got["then_ai"] or got["followed_by"]:
            return None
        return _enqueue_ai(conn, got, row)
    except Exception as exc:  # noqa: BLE001 - the rule check's result stands
        log.warning("review follow-up not started: %s", type(exc).__name__)
        return None


def _note(conn, run_id: str, text: str) -> None:
    with conn:
        conn.execute(
            f"UPDATE {review_engine.TABLE} SET followed_by = ? WHERE run_id = ?",
            (text, run_id),
        )


def _enqueue_ai(conn, got: dict, job) -> str | None:
    run_id, doc = got["run_id"], job["document_id"]
    scope = review_jobs._scope_of(job["created_by"])
    if not agent_review_gate.enabled():
        _note(conn, run_id, "not started: the AI review is switched off")
        return None
    # The plan is made again: approvals and caps may have changed since the button was pressed. A part that is no longer
    # allowed is not started, and the record says why in words.
    again = review_engine.plan_for(conn, doc, scope, got["choice"])
    ai = next(p for p in again["parts"] if p["name"] == review_engine.AI_REVIEW)
    if again["refused"] or ai["engine"] not in (
        review_engine.ON_CLAUDE,
        review_engine.ON_LOCAL,
    ):
        _note(conn, run_id, f"not started: {ai['why']}")
        return None
    on_local = ai["engine"] == review_engine.ON_LOCAL  # a local AI review is barred from Claude for its whole length
    plan = got["plan"]
    general = agent_review_gate.general_kind_enabled(again.get("kind"))
    projects = tuple(plan.get("project_document_ids") or ()) if general else None

    def choice_with_the_job(txn_conn, new_run_id: str) -> None:
        review_engine.record_in(
            txn_conn,
            new_run_id,
            again,
            job["created_by"],
            then_ai=False,
            bar_claude=on_local,
            now=job_queue.now_iso(),
        )

    try:
        ai_run, _ = agent_review_jobs.enqueue(
            doc,
            allowed_document_ids=scope,
            requested_by=job["created_by"],
            project_document_ids=projects,
            fresh=bool(plan.get("fresh")),
            in_transaction=choice_with_the_job,
        )
    except review_jobs.ReviewAlreadyActive:
        _note(
            conn, run_id, "not started: another review of this paper is already running"
        )
        return None
    _note(conn, run_id, ai_run)
    return ai_run
