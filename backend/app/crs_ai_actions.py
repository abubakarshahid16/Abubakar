"""What the contractor is asked, and what the AI reviewer says, on a Query of the AI reviewer's CRS comment (U5, P4 and P5).

The ACTION follows what the line HOLDS about the value, decided by code and never by the reader's words (P4): a value stated on the paper
(a quote code verified) is confirmed or justified, never "stated" again; a value the sheet defers is provided, and the sentence says it is
deferred; a blank field is stated; when code cannot tell, the engineer checks and the contractor is not asked. The comment's second line
carries the AI reviewer's own reasoning, labelled as its view (P5); a proven Pass or Fail has none. No model, no network."""

from __future__ import annotations

from collections.abc import Mapping

from . import agent_review_two_reader as two
from . import crs_ai_words as words
from .agent_review_verdict import SILENCE_CODES, SILENCE_WHY, quote_defers

_SAYS = (words.STATUS_AI, words.STATUS_AI_VERDICT, words.STATUS_QUERY)
REASONING_LABEL = "The AI reviewer's reasoning (not proven by code):"


def action_case(line: Mapping) -> str:
    """The case: "stated" (a paper quote code verified), "deferred" (the stored reason says so, or the verified quote defers the value), "blank"
    (the paper is silent on the field) or "unknown"."""
    if two.disagrees(line) or two.absence_disagrees(line):
        return "disagree"  # the two readers reached opposite verdicts: code's own flag
    checked = (line.get("quotes_checked") or {}).get("paper")
    verified = bool(checked and " ".join(str(line.get("paper_quote") or "").split()))
    if line.get("reason_code") == "value_deferred":
        return "deferred"
    if verified and quote_defers(line.get("paper_quote")):
        return "deferred"
    if verified:
        return "stated"
    silent = line.get("reason_code") in SILENCE_CODES or line.get("silence_query")
    if silent or line.get("verdict_label") == two.WORD_NOT_STATED:
        return "blank"
    return "unknown"


STATED_REASON = "a value is stated on the paper (a quote code verified); it is not proven that it meets the rule"


def reason_for(line: Mapping, why: str) -> str:
    """The reason shown with a line, made to agree with what code verified: a value STATED on the paper (a verified quote) means the sheet
    is not silent, so a stored "the paper is silent" reason is not shown (the action and the reason say the same)."""
    silent = line.get("reason_code") in SILENCE_CODES or line.get("silence_query")
    silent = silent or SILENCE_WHY.rstrip(".").lower() in str(why or "").lower()
    return STATED_REASON if silent and action_case(line) == "stated" else why


def query_action(line: Mapping, what: str, ref: str) -> str:
    """Part 3 of a Query: the sentence for the case the line is in."""
    case = action_case(line)
    if case == "stated":
        return f"Contractor to confirm or justify {what}{' against ' + ref if ref else ''}."
    if case == "deferred":
        return f"Contractor to provide {what}; it is deferred on the sheet."
    if case == "disagree":
        return f"Engineer to check {what}: the readers disagree."
    if case == "unknown":
        return f"Engineer to check {what}."
    return f"Contractor to state {what}, or the page where it is shown."


def reasoning_part(line: Mapping, status: str, guard: str) -> str:
    """The AI reviewer's own reasoning, plain and labelled as its view, for an opinion, a two-reader verdict or a Query; "" for a proven
    line, and "" when a guard's own view sentence is already printed."""
    if guard or status not in _SAYS:
        return ""
    # the AI's own `reasoning`, WHOLE (no character cut: a cell is never cut without the mark and its full text); never the model's
    # contractor-facing `comment` under this label
    view = words.plain(" ".join(str(line.get("reasoning") or "").split()))
    return f" {REASONING_LABEL} {view}" if view else ""
