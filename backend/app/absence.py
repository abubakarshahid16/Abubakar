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

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

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

THRESHOLDS_PATH = Path(__file__).parent / "reference" / "review_thresholds.json"
DEFAULT_UNCHECKED_SHARE_LIMIT = 0.5


def unchecked_share_limit() -> float:
    """Past this share of a run's in-scope requirements NOT compared (standards
    table values with no matching field, and requirements about other
    equipment), the run can not be approved: most of what the standards ask was
    not checked against this submittal, and an approval would be a claim about
    the rest. A policy choice, not a measurement: it lives in
    `reference/review_thresholds.json` so the owner can change it without a
    code change. An unreadable or out-of-range value falls back to 0.5 and is
    logged, never to "no limit"."""
    try:
        value = float(json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))["unchecked_share_limit"])
        if 0 < value <= 1:
            return value
        raise ValueError("outside (0, 1]")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        _log.warning("review_thresholds.json unchecked_share_limit unusable (%s); using %s",
                     type(exc).__name__, DEFAULT_UNCHECKED_SHARE_LIMIT)
        return DEFAULT_UNCHECKED_SHARE_LIMIT


def share_sentence(not_compared: int, not_applied: int, checked: int) -> str | None:
    """The three honest groups, then the share that matters: "Of T requirements
    in scope: C checked, N apply but were not checked, D do not apply. N of A
    (P%) of the requirements that apply were not checked." None when no
    requirement applies (nothing to take a share of). `not_applied` is shown
    but never part of the share (#678)."""
    share = unchecked_share(not_compared, checked)
    if share is None:
        return None
    nc, na, ck = (not_compared or 0), (not_applied or 0), (checked or 0)
    return (f"Of {nc + na + ck} requirements in scope: {ck} checked, {nc} apply but were not "
            f"checked, {na} do not apply. {nc} of {nc + ck} ({round(share * 100)}%) of the "
            "requirements that apply were not checked.")


def unchecked_share(not_compared: int, checked: int) -> float | None:
    """Share of the requirements that APPLY that were not checked, or None when
    none apply (nothing to take a share of). Requirements that do not apply are
    not in it, on either side (#678)."""
    applies = (not_compared or 0) + (checked or 0)
    if applies <= 0:
        return None
    return (not_compared or 0) / applies


def split_lines(split: dict | None) -> list[str]:
    """The reasons behind the two groups that have one, as plain lines, most
    common first (the CRS prints the top three of each)."""
    if not split:
        return []
    lines = []
    for title, key, count_key in (
            ("Apply but not checked", "applies_not_checked_reasons", "applies_not_checked"),
            ("Do not apply", "does_not_apply_reasons", "does_not_apply")):
        reasons = split.get(key) or []
        if not split.get(count_key):
            continue
        top = reasons[:3]
        more = len(reasons) - len(top)
        text = "; ".join(f"{r['reason']} ({r['count']})" for r in top)
        lines.append(f"{title} ({split[count_key]}): {text or 'no reason recorded'}"
                     + (f"; and {more} more reason(s)" if more > 0 else "") + ".")
    return lines


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

    def add(part: str, line: str, detail: bool = False) -> None:
        # `detail` lines explain another part (the reasons behind the unchecked
        # share); they are listed on the internal copy and are not counted as
        # parts that could not be checked.
        parts.append({"part": part, "line": line, **({"detail": True} if detail else {})})

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
    # THE SHARE, WITH ITS DENOMINATOR, on every incomplete export.
    counts = outcome.get("unchecked_counts") or {}
    sentence = share_sentence(counts.get("not_compared", 0), counts.get("not_applied", 0),
                              counts.get("checked", 0)) if counts else None
    # #678: only requirements that APPLY and were not checked make a sheet
    # incomplete. Ones that do not apply are in the sentence, as a count.
    if sentence and counts.get("not_compared", 0):
        add("unchecked_share", sentence)
        from . import requirement_split

        for line in split_lines(outcome.get("requirement_split") or requirement_split.from_counts(counts)):
            add("requirement_reasons", line, detail=True)
    elif parts and not counts:
        add("unchecked_share", "The share of requirements not compared is not known: "
                               "this review did not reach the comparison.")
    return parts


def notice_for(parts: list[dict]) -> str:
    """The one line a sheet prints when something could not be checked."""
    if not parts:
        return ""
    parts = [p for p in parts if not p.get("detail")]
    notice = (f"REVIEW INCOMPLETE: {len(parts)} part(s) could not be checked "
              "- this sheet is not a complete review.")
    # The unchecked share, with its denominator, is part of the notice on every
    # copy (#633, owner decision 2026-10-09).
    share = next((p["line"] for p in parts if p["part"] == "unchecked_share"), "")
    return f"{notice} {share}" if share else notice
