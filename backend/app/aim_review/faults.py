"""A FAILED STEP IS REPORTED (order 14, planner 26 Nov 2026 03:35, item D2; builder H). Where a read or check step of the general
review catches a fault so that the review goes on (a stored table that cannot be read, a code check that raises), the fault is not
only logged: it becomes one row of the run's calls, with no model and no cost, `ok` false and the code "<what> not applied: <why>".
The run keeps it (`calls_json`), and the page and the team file say it in plain words under "Steps that did not run"
(`aim_review_view.steps_not_applied`): the reader is never left to take a step that did not run as a step that found nothing.

The engine binds the run's own call list for the length of the run (`recording`); the judge's worker threads copy the context
(`aim_review.parallel`), so a step records from any of them. Outside a run (the plan, a test) `record` only logs. The row holds the
fault's class name and the step's own words, never document text.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar

log = logging.getLogger(__name__)

_CALLS: ContextVar[list | None] = ContextVar("aim_review_fault_calls", default=None)


@contextmanager
def recording(calls: list):
    """Faults recorded while this is open go to `calls` (the run's meter calls)."""
    token = _CALLS.set(calls)
    try:
        yield calls
    finally:
        _CALLS.reset(token)


@contextmanager
def during_run(run_id: str, calls: list):
    """The general review's own context for one run: its lines in the spend ledger (`claude_spend.for_run`), the papers it may
    send (`claude_approved.reviewing`), and this record of failed steps (`recording`)."""
    from app import claude_approved, claude_spend

    with (
        claude_spend.for_run(run_id),
        claude_approved.reviewing(run_id),
        recording(calls),
    ):
        yield calls


def why_of(exc: BaseException | str) -> str:
    """The fault's class name (never its message: a message can quote a paper); a plain reason is kept as it is."""
    return type(exc).__name__ if isinstance(exc, BaseException) else str(exc)


def record(step: str, what: str, exc: BaseException | str) -> None:
    """One row of the run's calls for a step that did not run: step `step`, code "<what> not applied: <why>"."""
    from .engine import CallRecord

    why = why_of(exc)
    log.warning("general review: %s not applied (%s)", what, why)
    calls = _CALLS.get()
    if calls is not None:
        calls.append(
            CallRecord(
                step=step,
                model="code",
                prompt_chars=0,
                ok=False,
                code=f"{what} not applied: {why}",
            )
        )
