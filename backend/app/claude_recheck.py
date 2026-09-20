"""Recheck findings: the model gives a SECOND OPINION on an engine verdict, and
Python decides what that opinion may do - which is almost nothing.

WHAT THIS IS. `comparison.compare` puts a standard's requirement beside a
datasheet value and writes a finding with a `compliance_status`. This module
shows the model the requirement sentence, the clause, the matched field, the
value with its unit and the engine's verdict, and asks one question: DO YOU
AGREE, AND IF NOT, WHY. The answer is shown to an engineer beside the finding.
That is the whole product: a reviewer with two hundred rows wants to know
which ten the model would argue about, not a second set of verdicts.

WHY A MODEL AT ALL, when section 14 of `comparison.py` says Python decides.
Because the engine is right about arithmetic and blind to reading: it will
compare a number from a lookup table against a limit if the parser mis-shaped
the sentence, and it cannot notice that "not less than" was read backwards
three modules upstream. The model is good at exactly that kind of noticing and
is not trusted to be right about it, which is what `accept()` is for.

HOW THIS SITS BESIDE `comparison._reconcile`. `_reconcile(deterministic,
model_opinion)` already exists and already carries the rule: the deterministic
result wins, and a model opinion that differs is RECORDED into `ai_rationale`
as a sentence, never applied. That reconciliation runs INSIDE `create_finding`,
at write time, on an opinion the caller supplied BEFORE the verdict existed.
This module is the same rule applied AFTER the finding exists - the model has
seen the engine's verdict and its inputs, which `_reconcile`'s opinion never
did. It does not feed `_reconcile` (that would mean rewriting the finding
through `create_finding`, which deletes nothing and would produce a duplicate)
and it does not extend `_reconcile`'s status vocabulary. It uses the same
column `_reconcile` writes to - `ai_rationale`, the column that exists so a
reader can see WHY the system said what it said - and the same posture: the
disagreement is stored as words, the status is not overruled. The one extra
thing a recheck may do that `_reconcile` may not is RAISE a COMPLIANT or
NON_COMPLIANT finding to NEEDS_ENGINEER_REVIEW, and only that direction.

THE HARD RULES, ENFORCED IN CODE, NOT ONLY ASKED FOR IN THE PROMPT.

  1. THE MODEL NEVER CHANGES A STATUS, AND NEVER TO COMPLIANT. A proposal
     carrying any status field is rejected outright (`status_change_attempted`)
     - the model was not asked for one, and an answer that volunteers one is
     an answer trying to do the engine's job. A disagreement does two things
     only: (a) records the model's opinion, and (b) raises the finding to
     NEEDS_ENGINEER_REVIEW when the engine said COMPLIANT or NON_COMPLIANT
     and the disagreement survived the gate. MISSING_INFORMATION, CONDITIONAL,
     NOT_APPLICABLE and NEEDS_ENGINEER_REVIEW are not raised: there is no
     verdict there to overturn, and a queue full of "the model disagrees that
     the field is blank" buries the rows that matter. Agreement records
     nothing but the agreement.
  2. THE MODEL QUOTES THE WORDS IT RELIES ON. `quote` must be inside the
     requirement sentence, folded, whole-word (`reader_api._contains`). This
     is the fabrication catch: an argument about a sentence that is not there
     has no true quote to give.
  3. EVERY NUMBER IN THE REASON IS A NUMBER FROM THE INPUTS - the requirement
     text, the value, the unit, the clause. "9,400 exceeds 8,300" is a reason
     an engineer can check; "the limit is really 6,500" is a number the model
     brought with it, and it is refused (`number_not_in_inputs`).
  4. TWO RUNS MUST AGREE ON AGREE/DISAGREE (`model_unstable`). A
     disagreement only one run produced is not one the inputs compel - rule 5
     of `reader_api.read_sentence`, kept for the same reason.

REQUIREMENT STATES FOR THE CRS. Every requirement ends in exactly one of five
states, because a Comment Resolution Sheet has to say for each row whether the
engine did its job, and "NEEDS_ENGINEER_REVIEW" alone conflates "we compared
and want a second look" with "we could not compare at all". The decision table
is in `requirement_state`.

THE MODEL IS INJECTED AS A CALLABLE (prompt -> raw text), as `reader_api` and
`extraction_llm` do. This module imports no HTTP client and opens no socket
(`test_socket_containment.py` globs the package); every test runs against a
fake callable.
"""

from __future__ import annotations

import json
from enum import Enum

from . import comparison
from .db import connect
from .reader_api import _NUMBER, _contains, _fold, _fold_numbers

# --------------------------------------------------------------- vocabulary

EVALUATED = "EVALUATED"
MISSING_EVIDENCE = "MISSING_EVIDENCE"
NOT_APPLICABLE = "NOT_APPLICABLE"
ENGINEER_JUDGMENT = "ENGINEER_JUDGMENT"
BLOCKED = "BLOCKED"

#: The five requirement states, and no sixth.
STATES = (EVALUATED, MISSING_EVIDENCE, NOT_APPLICABLE, ENGINEER_JUDGMENT, BLOCKED)

#: The statuses a disagreement may RAISE. Nothing else: the other four carry
#: no verdict for the model to argue with (hard rule 1).
RAISABLE = frozenset({comparison.COMPLIANT, comparison.NON_COMPLIANT})

#: The exact prefix every stored note carries. A reader grepping
#: `ai_rationale` for this string finds every recheck and nothing else, and
#: the words say what the note is: an opinion awaiting a human, never a
#: decision.
NOTE_PREFIX = "Rechecked by model; engineer must confirm. "

#: The engine's own refusal markers, as written at the head of `ai_rationale`
#: by `comparison`. Each is "the engine could not evaluate this at all",
#: which is BLOCKED and not ENGINEER_JUDGMENT: no comparison was made, so
#: there is no judgment to exercise, only an input to fix.
_BLOCKING_REASONS = (
    comparison.UNIT_MISMATCH,
    comparison.TABLE_ROW_REASON,
    comparison.RELATIVE_LIMIT_REASON,
)
#: The unit-mismatch-with-no-conversion refusal from `comparison.compare`
#: is written as a sentence rather than with the marker; matched on its own
#: fixed words.
_NO_CONVERSION_PHRASE = "cannot be compared by this system; no conversion is guessed"

#: JSON keys that would be a status change. Any of them, any value.
_STATUS_KEYS = ("status", "compliance_status", "verdict", "new_status")


class Reason(Enum):
    """Why a recheck proposal was thrown away. A NAMED REASON, ALWAYS,
    on `reader_api.Reason`'s pattern: a plain Enum, `.value` everywhere."""

    #: Not the JSON asked for. Call-level: nothing was read.
    MODEL_MALFORMED = "model_malformed"
    #: Hard rule 2. The quote is not in the requirement sentence.
    QUOTE_NOT_IN_SENTENCE = "quote_not_in_sentence"
    #: A disagreement with no reason is an opinion nobody can check.
    REASON_MISSING = "reason_missing"
    #: Hard rule 3. A number in the reason that no input carries.
    NUMBER_NOT_IN_INPUTS = "number_not_in_inputs"
    #: Hard rule 4. Two runs did not agree on agree/disagree.
    MODEL_UNSTABLE = "model_unstable"
    #: Hard rule 1. The JSON tried to set a status.
    STATUS_CHANGE_ATTEMPTED = "status_change_attempted"


# ------------------------------------------------------- requirement state

def requirement_state(finding: dict) -> str:
    """The one CRS state for this finding. A PURE MAPPING, no I/O.

    DECISION TABLE, in the order it is applied:

      citation does not resolve          -> BLOCKED
        (`unresolved_evidence` non-empty: `create_finding` downgraded it)
      engine refused to compare          -> BLOCKED
        (`ai_rationale` opens with `unit_mismatch:`, `table_row:` or
        `relative_limit:`, or states the no-conversion refusal)
      COMPLIANT / NON_COMPLIANT / CONDITIONAL -> EVALUATED
      MISSING_INFORMATION                -> MISSING_EVIDENCE
      NOT_APPLICABLE                     -> NOT_APPLICABLE
      NEEDS_ENGINEER_REVIEW              -> ENGINEER_JUDGMENT
        (ambiguous match, range against an exact value, a limit the engine
        could not read, or a finding raised by this module: a comparison
        was attempted or a pairing exists, and a human decides)
      anything else, including NULL      -> BLOCKED

    BLOCKED is checked BEFORE the status because the engine's refusals are
    all stored as NEEDS_ENGINEER_REVIEW, and the difference between "an
    engineer must judge this" and "nothing here could be evaluated" is the
    difference the CRS exists to show.
    """
    unresolved = finding.get("unresolved_evidence")
    if isinstance(unresolved, str):
        try:
            unresolved = json.loads(unresolved or "[]")
        except (TypeError, ValueError):
            unresolved = [unresolved]
    if unresolved:
        return BLOCKED
    rationale = _fold(finding.get("ai_rationale") or "")
    if any(rationale.startswith(f"{marker}:") for marker in _BLOCKING_REASONS):
        return BLOCKED
    if _NO_CONVERSION_PHRASE in rationale:
        return BLOCKED
    return {
        comparison.COMPLIANT: EVALUATED,
        comparison.NON_COMPLIANT: EVALUATED,
        comparison.CONDITIONAL: EVALUATED,
        comparison.MISSING_INFORMATION: MISSING_EVIDENCE,
        comparison.NOT_APPLICABLE: NOT_APPLICABLE,
        comparison.NEEDS_ENGINEER_REVIEW: ENGINEER_JUDGMENT,
    }.get(finding.get("compliance_status"), BLOCKED)


# ------------------------------------------------------------------- prompt

PROMPT = """You are giving a SECOND OPINION on one compliance finding that a
deterministic engine already made. You are NOT asked for a verdict and you
may not change the status. An engineer will read your answer beside the
engine's.

Answer as JSON only:
{"agree": true|false, "quote": "...", "reason": "<one sentence>"}

agree  - true if the engine's verdict follows from the requirement sentence
         and the submitted value; false if you think it does not.
quote  - the EXACT words of the requirement sentence you relied on, copied
         character for character. Never a quote that is not in the sentence.
reason - one sentence. Every number you mention must be one that appears
         in the requirement, the value, the unit or the clause below. Do not
         introduce a number of your own.

Do NOT include a status field. Do not decide compliance.

"""


def _sentence(finding: dict) -> str:
    """The requirement sentence: the source text when the finding carries it,
    else the requirement column. Both are the standard's own words."""
    return (finding.get("requirement_source_text")
            or finding.get("requirement") or "").strip()


def _value(finding: dict) -> str:
    return str(finding.get("value")
               if finding.get("value") not in (None, "")
               else finding.get("contractor_evidence_text") or "").strip()


def _unit(finding: dict) -> str:
    return str(finding.get("unit") or finding.get("raw_unit") or "").strip()


def build_prompt(finding: dict) -> str:
    """The prompt for one finding: sentence, clause, matched field, value,
    unit, and the engine's verdict with its rationale."""
    return PROMPT + "\n".join([
        f"REQUIREMENT: {_sentence(finding)}",
        f"CLAUSE: {finding.get('standard_clause') or ''}",
        f"MATCHED FIELD: {finding.get('matched_phrase') or ''}",
        f"SUBMITTED VALUE: {_value(finding)}",
        f"UNIT: {_unit(finding)}",
        f"ENGINE VERDICT: {finding.get('compliance_status') or ''}",
        f"ENGINE RATIONALE: {finding.get('ai_rationale') or ''}",
    ])


# -------------------------------------------------------------------- parse

def parse_response(raw: str) -> tuple[dict | None, str | None]:
    """Strict parse. `(proposal, None)` or `(None, "model_malformed")`.

    Never repaired: half-JSON turned into a proposal is the module inventing
    an opinion and calling it the model's.
    """
    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, Reason.MODEL_MALFORMED.value
    if not isinstance(body, dict) or not isinstance(body.get("agree"), bool):
        return None, Reason.MODEL_MALFORMED.value
    proposal = {
        "agree": body["agree"],
        "quote": str(body.get("quote") or ""),
        "reason": str(body.get("reason") or "").strip(),
    }
    for key in _STATUS_KEYS:
        if key in body:
            # Carried through so `accept` can NAME the attempt rather than
            # this parser quietly dropping the field and letting the rest
            # of the answer through.
            proposal["status_attempted"] = body[key]
            break
    return proposal, None


# --------------------------------------------------------------- the gate

def _numbers(text) -> set[float]:
    return {float(n) for n in _NUMBER.findall(_fold_numbers(text or ""))}


def _input_numbers(finding: dict) -> set[float]:
    """Every number the inputs carry (hard rule 3's allowed set)."""
    out: set[float] = set()
    for text in (
        _sentence(finding), finding.get("requirement"),
        _value(finding), _unit(finding), finding.get("standard_clause"),
    ):
        out |= _numbers(str(text or ""))
    return out


def accept(proposal: dict, finding: dict) -> dict:
    """THE GATE. `{"accepted": proposal|None, "rejected": [...], "counts"}`.

    Kept only when ALL of these hold: no status was attempted; the quote is
    inside the requirement sentence; a disagreement carries a reason; every
    number in the reason appears in the inputs. An agreement's reason is not
    required - agreement records nothing but the agreement - but when given
    it is still checked for invented numbers, because it is shown to an
    engineer.
    """
    rejected: list[dict] = []

    def drop(reason: Reason) -> dict:
        # The model's own sentence is kept as `model_reason`; `reason` is
        # the gate's, so `rejection_counts`-style tallies read one key.
        rejected.append({**proposal, "model_reason": proposal.get("reason"),
                         "reason": reason.value})
        return {"accepted": None, "rejected": rejected,
                "counts": {reason.value: 1}}

    if "status_attempted" in proposal:
        return drop(Reason.STATUS_CHANGE_ATTEMPTED)
    quote = _fold(proposal.get("quote") or "")
    if not quote or not _contains(_fold(_sentence(finding)), quote):
        return drop(Reason.QUOTE_NOT_IN_SENTENCE)
    if not proposal["agree"] and not proposal.get("reason"):
        return drop(Reason.REASON_MISSING)
    if not _numbers(proposal.get("reason")) <= _input_numbers(finding):
        return drop(Reason.NUMBER_NOT_IN_INPUTS)
    return {"accepted": proposal, "rejected": [], "counts": {}}


# ------------------------------------------------------------ the two runs

def _empty(finding: dict, error: str | None = None, rejected=None) -> dict:
    rejected = list(rejected or [])
    counts: dict = {}
    for r in rejected:
        counts[r["reason"]] = counts.get(r["reason"], 0) + 1
    out = {"agree": None, "reason": None, "quote": None, "rejected": rejected,
           "counts": counts, "state": requirement_state(finding),
           "raise_to_engineer": False}
    if error:
        out["error"] = error
    return out


def recheck_finding(finding: dict, model_call, second_call=None) -> dict:
    """One finding through the model TWICE and then through the gate.

    Returns `{"agree", "reason", "quote", "rejected", "counts", "state",
    "raise_to_engineer"}`, plus `error` when an answer was not JSON. `agree`
    is None whenever nothing survived, and `raise_to_engineer` is True ONLY
    for a surviving disagreement on a COMPLIANT or NON_COMPLIANT finding
    (hard rule 1). `state` is `requirement_state(finding)` and is not
    changed by the model's answer - the state describes what the ENGINE
    could do.
    """
    first, err = parse_response(model_call(build_prompt(finding)))
    if err:
        return _empty(finding, error=err)
    again = second_call if second_call is not None else model_call
    second, err2 = parse_response(again(build_prompt(finding)))
    if err2:
        return _empty(finding, error=err2)
    if first["agree"] != second["agree"]:
        return _empty(finding, rejected=[
            {**first, "reason": Reason.MODEL_UNSTABLE.value}])
    gate = accept(first, finding)
    if gate["accepted"] is None:
        return _empty(finding, rejected=gate["rejected"])
    p = gate["accepted"]
    return {
        "agree": p["agree"],
        "reason": p.get("reason") or None,
        "quote": p["quote"],
        "rejected": [], "counts": {},
        "state": requirement_state(finding),
        "raise_to_engineer": (not p["agree"]
                              and finding.get("compliance_status") in RAISABLE),
    }


def recheck_run(review_run_id: str, model_call, *,
                allowed_document_ids: frozenset[str],
                findings: list[dict] | None = None,
                second_call=None) -> dict:
    """Every finding of a run, with counts a reviewer can read at a glance.

    `findings` is injectable so the aggregation is testable without a
    database; by default it is `comparison.list_findings`, under the caller's
    grants. Nothing is stored here - `store_recheck` is a separate, thin step
    so a caller can look before writing.
    """
    if findings is None:
        findings = comparison.list_findings(
            review_run_id, allowed_document_ids=allowed_document_ids)
    results: dict[str, dict] = {}
    agreed = disagreed = raised = 0
    rejected_by_reason: dict[str, int] = {}
    states = {state: 0 for state in STATES}
    for finding in findings:
        result = recheck_finding(finding, model_call, second_call)
        results[finding.get("id")] = result
        states[result["state"]] += 1
        if result.get("error"):
            rejected_by_reason[result["error"]] = rejected_by_reason.get(result["error"], 0) + 1
        for reason, n in result["counts"].items():
            rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + n
        if result["agree"] is True:
            agreed += 1
        elif result["agree"] is False:
            disagreed += 1
            raised += int(result["raise_to_engineer"])
    return {"review_run_id": review_run_id, "findings": results,
            "agreed": agreed, "disagreed": disagreed, "raised": raised,
            "rejected": rejected_by_reason, "states": states,
            "total": len(findings)}


# ------------------------------------------------------------------- store

def note_for(result: dict) -> str | None:
    """The stored note, or None when there is nothing to store.

    A rejected recheck stores nothing: a note saying "the model was rejected
    for inventing a number" is a fact about the model, not about the finding.
    """
    if result.get("agree") is None:
        return None
    if result["agree"]:
        return NOTE_PREFIX + "Model agrees with the engine's verdict."
    return (NOTE_PREFIX + "Model disagrees: " + (result.get("reason") or "")
            + f' (quoting: "{result.get("quote") or ""}")')


def store_recheck(finding_id: str, result: dict) -> dict | None:
    """Write the note into `ai_rationale`; raise the status only per rule 1.

    `ai_rationale` is the column `_reconcile`'s disagreement already lands
    in: it is the "why the system said this" column, shown beside the
    finding and never the finding itself. No new column, no migration.

    NEVER TOUCHES A FINDING AN ENGINEER HAS DECIDED - `confirmed_by` or
    `disposition` set. A human's decision outranks both the engine and the
    model, and `review_findings` grew `confirmed_by` precisely so that
    maintenance actions cannot undo one (see `review.ensure_schema`).

    Returns `{"stored": bool, "raised": bool, "why": ...}`, or None when no
    such finding exists.
    """
    conn = connect()
    row = conn.execute(
        "SELECT compliance_status, ai_rationale, confirmed_by, disposition"
        " FROM review_findings WHERE id = ?", (finding_id,)).fetchone()
    if row is None:
        return None
    if row["confirmed_by"] or row["disposition"]:
        return {"stored": False, "raised": False, "why": "engineer_decided"}
    note = note_for(result)
    if note is None:
        return {"stored": False, "raised": False, "why": "rejected"}
    raise_it = (result.get("agree") is False
                and result.get("raise_to_engineer") is True
                and row["compliance_status"] in RAISABLE)
    rationale = f"{row['ai_rationale'] or ''} {note}".strip()
    sets = ["ai_rationale = ?", "updated_at = ?"]
    args: list = [rationale, comparison._now()]
    if raise_it:
        sets += ["compliance_status = ?", "required_action = ?"]
        args += [comparison.NEEDS_ENGINEER_REVIEW,
                 comparison._required_action(comparison.NEEDS_ENGINEER_REVIEW)]
    with conn:
        conn.execute(
            f"UPDATE review_findings SET {', '.join(sets)} WHERE id = ?",
            [*args, finding_id])
    return {"stored": True, "raised": raise_it,
            "why": "disagreed" if result["agree"] is False else "agreed"}


__all__ = [
    "BLOCKED", "ENGINEER_JUDGMENT", "EVALUATED", "MISSING_EVIDENCE",
    "NOTE_PREFIX", "NOT_APPLICABLE", "PROMPT", "RAISABLE", "STATES",
    "Reason", "accept", "build_prompt", "note_for", "parse_response",
    "recheck_finding", "recheck_run", "requirement_state", "store_recheck",
]
