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


#: (Moved from `aim_review_view`, update 9, to keep that file under its size limit.) What a run's checking step that did not run means for the sheet, in plain words (a failed AI step is shown and never makes a
#: comment more confident: its lines stay as the step before left them).
NOT_APPLIED_WORDS = {
    "aim_second_read": "The second reader did not run on this sheet ({why}): its findings are sent as the first reader judged "
    'them, none is marked "two readers agree".',
    "aim_answered": "The whole-paper check did not run on this sheet ({why}): no comment was taken off for a claim the paper "
    "contradicts.",
    "aim_edit": "The editor did not run on this sheet ({why}): repeated comments are not grouped or taken off.",
    # code steps that fail and let the review go on (planner 26 Nov 2026, D2: a failed step is reported; `aim_review.faults`)
    "aim_unread_check": "The check of which pages were read did not run on this sheet ({why}): pages with no text are not "
    "named, so do not take every page as read.",
    "aim_picture_readings": "The stored picture readings could not be read ({why}): every picture is named as not read.",
    "aim_g1_facts": "The library facts for the cited-standards check (G1) were not read ({why}): G1 was judged on the paper "
    "alone.",
    "aim_contract_code": "A code check of the contract did not run on this sheet ({why}): the points it checks are not "
    "checked by code.",
    "aim_contract_schedules": "The package's Schedules could not be read ({why}): no line about the package's Schedules "
    "was written.",
    "aim_book_reasons": "The table's reasons for the rule books were not read ({why}): a rule book the scope step gave no "
    "reason for says the reason was not recorded.",
    "aim_checklist_keys": "The list of saved checklists could not be read ({why}): the paper was named without the saved "
    "checklist types to choose from.",
    "aim_formula_checks": "The formula checks did not run in full on this sheet ({why}): a limit a held standard states may not "
    'have been checked by code, so do not read "no formula line" as "nothing found".',
    "aim_checklist_save": "The checklist was not saved for reuse ({why}); this sheet was judged on it all the same.",
    # the local model's set-asides (review of update 9, M5): a cut answer is never used, and each one is counted here
    "aim_checklist_cut": "{n} checklist batch{es} gave no items ({why}): the rules in {it} were not made checklist items.",
    "aim_attack_cut": "{n} attack batch{es} {was} not used ({why}): the checklist was not attacked on those rules.",
    "aim_retry_dropped": "{n} checklist item{s} {was} left out: {its} rule quote was not found on the book page, and the "
    "answer when asked again for the rule's exact words was not used ({why}).",
    "aim_retry_capped": "{n} checklist item{s} {was} left out without a second ask (the local model makes one retry call "
    "per batch): {why}.",
    "aim_retry_not_found": "{n} checklist item{s} {was} left out after a second ask: {why}.",
    "aim_attack_not_shown": "{n} checklist item{s} {was} not attacked ({why}) and {was} kept as the first engineer wrote "
    "{it}.",
    "aim_attack_knowledge": "{n} knowledge item{s} {was} not attacked ({why}).",
    "aim_attack_item_cut": "{n} checklist item{s} {was} not attacked ({why}) and {was} kept as the first engineer wrote "
    "{it}.",
    "aim_attack_no_verdict": "{n} checklist item{s} got no attack verdict ({why}) and {was} kept as the first engineer "
    "wrote {it}.",
    "aim_repeat_cut": "{n} checklist answer{s} repeated {itself} and {was} cut at the first repeat ({why}).",
}


#: The count words of the local set-asides' sentences, as (one, more than one).
_COUNT_WORDS = {"{es}": ("", "es"), "{s}": ("", "s"), "{was}": ("was", "were"), "{it}": ("it", "them"), "{its}": ("its", "their"),
                "{itself}": ("itself", "themselves")}  # fmt: skip


#: A local review recorded before its set-asides were counted by cause gave one fixed reason; said once, never twice (review of
#: update 11, N7).
LEGACY_WORDS = {
    (
        "aim_retry_capped",
        "the local model makes one retry call per batch",
    ): "{n} checklist item{s} {was} left out without a "
    "second ask (the local model makes one retry call per batch).",
}


def counted(words: str, n: int) -> str:
    """A NOT_APPLIED_WORDS sentence with its count `n`; the words of the other steps hold no count and are unchanged."""
    words = words.replace("{n}", str(n))
    for mark, (one, more) in _COUNT_WORDS.items():
        words = words.replace(mark, one if n == 1 else more)
    return words
