"""The independent cross-check of an AI reviewer line by a second AI of another company (Groq; owner decision 17 Nov 2026,
#1584; behind `groq_crosscheck_enabled`, default off). Pure functions on a stored line: no I/O, no model call.

THE RULE. The cross-check may only make a line LESS confident. A line it asked about carries the record `crosscheck`:

    {"asked": bool, "agree": True | False | None, "model": str | None, "usd": float, "reason": <= 20 words | None,
     "code": str | None, "said": str | None}

  * `agree` False on a line that is not proven by code (the gate's verdict is Query, the AI said met or not met): the line
    is a Query for the engineer with the reason `DISAGREE_WHY` (`agent_review_wording.classify`, step 2e);
  * `agree` True: evidence on the line (internal), nothing else changes;
  * no answer, not approved, not verified, a cap: nothing changes; `said` is the sentence the line shows after its reason.
A proven Pass or Fail (code compared a value or proved an absence) is never asked and never touched, whatever a record on
it says. The record's `reason` is the second AI's own words, at most 20, internal only: never a CRS cell.

The run step that asks is `agent_review_crosscheck_run.CrosscheckMixin`; the socket is `groq_transport`.
"""

from __future__ import annotations

from collections.abc import Mapping

from . import agent_review_code_proof as code_proof
from .agent_review_verdict import FAIL, PASS, QUERY

FIELD = "crosscheck"
DISAGREE_WHY = "an independent second AI (another company) disagrees"
NOT_APPROVED_SAID = "cross-check not run: paper not approved for the second AI"
NOT_VERIFIED_SAID = "cross-check not run: a quote was not verified by code"
CAP_SAID = "cross-check not run: the second AI's money cap is reached"
NO_ANSWER_SAID = "cross-check not run: the second AI gave no usable answer"
STOPPED_SAID = "cross-check not run: the step stopped"
TOO_LONG_SAID = "cross-check not run: quote too long"
SOURCE_UNKNOWN_SAID = (
    "cross-check not run: the document a quote comes from is not known"
)
NOT_SHOWN_SAID = (
    "cross-check not run: the second AI was not on the list shown before the start"
)


def record(line: Mapping) -> Mapping | None:
    got = line.get(FIELD)
    return got if isinstance(got, Mapping) else None


def answered(line: Mapping) -> bool:
    """The second AI gave a true or false answer for this line (it is never asked again on resume)."""
    rec = record(line)
    return bool(rec) and isinstance(rec.get("agree"), bool)


def unproven_ai_line(line: Mapping) -> bool:
    """An AI met or not met that code did not prove: the gate's verdict is Query and the line is not a code line."""
    return (
        line.get("ai_verdict") in (PASS, FAIL)
        and line.get("verdict") == QUERY
        and not line.get("error")
        and not code_proof.is_code_line(line)
    )


def disagrees(line: Mapping) -> bool:
    """The second AI was asked, answered false, and the line is an unproven AI line: it must be a Query."""
    rec = record(line)
    return bool(rec) and rec.get("agree") is False and unproven_ai_line(line)


def said(line: Mapping) -> str | None:
    """The sentence a line shows after its reason when the cross-check did not run for it (None otherwise)."""
    rec = record(line)
    if not rec or isinstance(rec.get("agree"), bool) or not unproven_ai_line(line):
        return None
    text = rec.get("said")
    return str(text) if text else None
