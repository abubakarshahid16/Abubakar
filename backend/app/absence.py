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


# ------------------------------------------------- a run that is not complete

#: Past this share of a run's in-scope requirements NOT compared (standards
#: table values with no matching field, and requirements about other
#: equipment), the run can not be approved: most of what the standards ask was
#: not checked against this submittal, and an approval would be a claim about
#: the rest. A policy choice, not a measurement: the owner can change it here.
UNCHECKED_SHARE_LIMIT = 0.5


def unchecked_share(not_compared: int, not_applied: int, checked: int) -> float | None:
    """Share of the in-scope requirements that were not compared, or None when
    there were none in scope at all (nothing to take a share of)."""
    total = (not_compared or 0) + (not_applied or 0) + (checked or 0)
    if total <= 0:
        return None
    return ((not_compared or 0) + (not_applied or 0)) / total


def check_failed_status(name: str, reason: str) -> dict:
    """The stored status of an optional check (AI, web) that could not run or
    failed: a fact on the run, never silence that reads as "nothing to raise"."""
    why = (reason or "").strip().rstrip(".") or "it did not complete"
    return {"ran": False, "complete": False, "calls_made": 0, "requested_items": 0,
            "proposed_items": 0, "kept_items": 0, "rejected": {}, "cost_usd": None,
            "reason": why, "plain": f"{name} could not be checked: {why}."}


def unchecked_parts(*, run_status: str | None, outcome: dict | None,
                    partial_findings: int = 0,
                    ai_status: dict | None = None,
                    web_status: dict | None = None) -> list[dict]:
    """The parts of a review that could NOT be checked, as plain lines.

    ONE LIST for every export: the CRS prints it, the internal review notes
    carry it, and a sheet is never exported looking complete when it is not.
    Each entry is {"part", "line"}; an empty list means nothing is known to be
    unchecked (not that the review is correct).
    """
    outcome = outcome or {}
    parts: list[dict] = []

    def add(part: str, line: str) -> None:
        parts.append({"part": part, "line": line})

    if run_status != "completed":
        why = (outcome.get("error") or "").strip().rstrip(".")
        add("run_not_completed",
            f"This review did not complete (status: {run_status or 'unknown'})"
            + (f": {why}" if why else "")
            + ". Any findings below are partial.")
    elif outcome.get("partial"):
        add("partial", "Some findings were written before the review stopped; they are partial.")
    if partial_findings and run_status != "completed":
        add("partial_findings",
            f"{partial_findings} finding(s) were written before the review stopped; "
            "they are partial and no review code was recommended.")
    if outcome.get("datasheet_check_not_run"):
        add("datasheet_check_not_run",
            "The datasheet revision-block check could not be checked: "
            + str(outcome["datasheet_check_not_run"]) + ".")
    stds = outcome.get("standards_not_checked") or []
    if stds:
        add("standards_not_checked",
            f"{len(stds)} standard(s) in scope had no requirement that could be checked "
            f"and were not checked: {', '.join(stds[:5])}"
            + (f" and {len(stds) - 5} more" if len(stds) > 5 else "") + ".")
    cells = sum(int(l.get("count") or 0) for l in outcome.get("table_values_not_compared") or [])
    if cells:
        add("table_values_not_compared",
            f"{cells} standards-table value(s) were not compared: no matching field on this submittal.")
    applied = sum(int(l.get("count") or 0) for l in outcome.get("requirements_not_applied") or [])
    if applied:
        add("requirements_not_applied",
            f"{applied} requirement(s) were not applied: they are about other equipment than this submittal.")
    held = (outcome.get("requirements_held_back") or {}).get("text_quality") or 0
    if held:
        add("text_quality_held_back",
            f"{held} requirement(s) were held back: their text could not be read reliably.")
    unread = (outcome.get("page_coverage") or {}).get("pages_not_read_into_fields") or []
    if unread:
        add("unread_pages", f"{len(unread)} page(s) of this submittal were not read into fields; "
                            "values on them could not be checked.")
    for key, status in (("ai_check", ai_status), ("web_check", web_status)):
        if status and status.get("complete") is False:
            add(key, str(status.get("plain") or f"{key} did not complete").strip())
    return parts


def notice_for(parts: list[dict]) -> str:
    """The one line a sheet prints when something could not be checked."""
    if not parts:
        return ""
    return (f"REVIEW INCOMPLETE: {len(parts)} part(s) could not be checked "
            "- this sheet is not a complete review.")
