"""ONE RULE FOR ABSENCE (#450, #451): not found is never a positive outcome.

A value that is missing, a page that was not read, a standard that is not held,
a side that failed or was stopped, a model that did not answer: none of these
is "compliant", "met", "not applicable" or "nothing there". Each is UNKNOWN or
NEEDS AN ENGINEER, with a plain reason, and the two kinds of "no" stay apart:

  * NOT FOUND: the search or the read RAN and the thing is not in what was
    read. Said as "not found in the pages read": a statement about the pages,
    never about the document or the contractor.
  * COULD NOT BE CHECKED: the check did not complete (stopped, failed, refused,
    out of budget, an answer that could not be supported). Said as "could not
    be checked: <reason>". It draws no verdict and is never worded as absence.

This module is the shared vocabulary and the shared decisions; the screens and
exports call it instead of each deciding for itself.
"""
from __future__ import annotations

ANSWERED = "answered"
NOT_FOUND = "not_found"
COULD_NOT_BE_CHECKED = "could_not_be_checked"

#: `absence_kind` an answer carries when its REFUSAL is a real absence: the
#: search ran and nothing fit, or the model read the sources and said they do
#: not contain it. Any other refusal is a failure to check, not an absence.
ABSENCE_KIND_NOT_FOUND = "not_found"

#: Answer types that are a finished answer.
_FINISHED_TYPES = frozenset({"extract", "generated", "comparison"})

STOPPED_REASON = "the run was stopped before this side was finished"


def not_found_text(name: str) -> str:
    return f"{name}: not found in the pages read."


def could_not_be_checked_sentence(reason: str | None) -> str:
    why = (reason or "").strip().rstrip(".") or "the check did not complete"
    return f"could not be checked: {why}."


def could_not_be_checked_text(name: str, reason: str | None) -> str:
    return f"{name}: {could_not_be_checked_sentence(reason)}"


def side_state(side: dict, used_passages: list) -> tuple[str, str | None]:
    """(state, reason) for one compared side's own answer.

    ANSWERED only for a finished answer that used passages. NOT_FOUND only when
    the side's search really ran and found nothing. Everything else, a stop, a
    failed or refused model, an answer that could not be supported, is COULD
    NOT BE CHECKED with the side's own reason.
    """
    kind = side.get("answer_type")
    reason = (side.get("reason") or "").strip() or None
    if kind == "cancelled":
        return COULD_NOT_BE_CHECKED, STOPPED_REASON
    if kind == "model_unavailable":
        return COULD_NOT_BE_CHECKED, reason or "the answer model was not available"
    if kind == "insufficient_evidence":
        if side.get("absence_kind") == ABSENCE_KIND_NOT_FOUND or reason is None:
            return NOT_FOUND, reason
        return COULD_NOT_BE_CHECKED, reason
    if kind in _FINISHED_TYPES:
        return (ANSWERED, None) if used_passages else (NOT_FOUND, reason)
    return COULD_NOT_BE_CHECKED, reason or f"the side returned no answer ({kind or 'unknown type'})"


#: Review statuses that are an ANSWER ABOUT THE REQUIREMENT. Anything else, an
#: unrecognised status, None, a status added later, counts as unresolved and can
#: never lead to an approval.
def is_unrecognised(status: object, recognised: frozenset[str]) -> bool:
    return status not in recognised


# ---------------------------------------------------------------- the review

#: The pairing model's outcomes that mean the step FAILED, as opposed to
#: "the model looked and no field fits" (`model_declined`) or "the model is
#: switched off" (`model_disabled`), which are ordinary absences.
_MODEL_FAILURES = frozenset({
    "model_unavailable", "model_malformed", "model_out_of_range",
    "model_unstable", "model_budget"})

_MODEL_FAILURE_WORDS = {
    "model_unavailable": "the model that pairs fields was not available",
    "model_malformed": "the model that pairs fields returned an answer that could not be read",
    "model_out_of_range": "the model that pairs fields named a field that does not exist",
    "model_unstable": "the model that pairs fields gave different answers on repeat",
    "model_budget": "the model that pairs fields was out of budget",
}


def pairing_not_checked(match_reason: str | None, model_reason: str | None,
                        rule_unread: str | None) -> str | None:
    """Why the step that pairs a requirement with a submitted field did NOT
    complete, or None when "no field answers this" really was established.

    A requirement with no paired field is MISSING INFORMATION only when the
    pairing ran and found nothing. If the pairing model failed, if a rule
    refused the only candidate, or if a table rule could not be read, the value
    may be on the sheet, and the answer is an engineer's question.
    """
    if match_reason == "refused_by_rule":
        return ("a field named in the requirement exists but a unit or domain "
                "rule refused to pair it")
    if model_reason in _MODEL_FAILURES:
        return _MODEL_FAILURE_WORDS[model_reason]
    if rule_unread:
        return str(rule_unread).strip().rstrip(".")
    return None
