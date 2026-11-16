"""What the contractor is asked, and what the AI reviewer says, on a Query of the AI reviewer's CRS comment (U5, P4 and P5).

The ACTION follows what the line HOLDS about the value, decided by code and never by the reader's words (P4): a value stated on the paper
(a quote code verified) is confirmed or justified, never "stated" again; a value the sheet defers is provided, and the sentence says it is
deferred; a blank field is stated; when code cannot tell, the engineer checks and the contractor is not asked. The comment's second line
carries the AI reviewer's own reasoning, labelled as its view (P5); a proven Pass or Fail has none. No model, no network."""

from __future__ import annotations

import re
from collections.abc import Mapping

from . import agent_review_two_reader as two
from . import crs_ai_words as words
from .agent_review_verdict import SILENCE_CODES, SILENCE_WHY, quote_defers

_SAYS = (words.STATUS_AI, words.STATUS_AI_VERDICT, words.STATUS_QUERY)
REASONING_LABEL = "The AI reviewer's reasoning (not proven by code):"


#: The reason a second-opinion reply stores when its answer was cut off by its token limit (`agent_review_run`).
CUT_OFF_REASONS = frozenset({"stop_max_tokens"})


def second_cut_off(line: Mapping) -> bool:
    """The line's second opinion was asked and its answer was CUT OFF (R101: the line's own marker, never the reason text): no true/false
    agree and reason "stop_max_tokens", or a retry that still gave no true/false answer. Lane A's `agent_review_two_reader.second_cut_off`
    holds the same rule; a test keeps the two equal once it is merged."""
    second = line.get("second_opinion")
    if not isinstance(second, Mapping) or isinstance(second.get("agree"), bool):
        return False
    if second.get("retried"):
        return (
            True  # the first reply was cut and its one retry gave no true/false answer
        )
    return (
        second.get("agree") is None
        and str(second.get("reason") or "").strip() in CUT_OFF_REASONS
    )


def action_case(line: Mapping) -> str:
    """The case: "stated" (a paper quote code verified), "deferred" (the stored reason says so, or the verified quote defers the value), "blank"
    (the paper is silent on the field) or "unknown"."""
    if second_cut_off(line):
        return "cut_off"  # R98/R101: the second reader's answer was cut off (its own marker): never "the readers disagree"
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


_STAR = re.compile(r"(?:^|[\s(])\*+(?=[\s)]|$)")


def sheet_mark(line: Mapping) -> str:
    """How the sheet marks a deferred value, from the quote code VERIFIED on the page (lane D): " (marked * on page N)" for a lone star,
    ' (marked "<its words>" on page N)', " (left open on page N)" with no verified quote; "" when not even the page is known."""
    from .agent_review_crs import stated

    has, page = stated(line), line.get("deferred_page") or line.get("paper_page")
    on = f" on page {page}" if page not in (None, "") else ""
    if has and _STAR.search(has):
        return f" (marked *{on})"
    return f' (marked "{has}"{on})' if has else (f" (left open{on})" if on else "")


def provisional(line: Mapping) -> bool:
    """The sheet prints a FIGURE with a unit beside its deferral mark ("340 psig By Contractor"): a provisional value to be confirmed, not
    a blank to be provided. Read by the app's one number reader (`claims.extract_measurements`) in the verified quote only."""
    from .claims import extract_measurements

    quote = (
        " ".join(str(line.get("paper_quote") or "").split())
        if (line.get("quotes_checked") or {}).get("paper")
        else ""
    )
    return bool(quote) and bool(extract_measurements(quote))


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
    if (
        case == "deferred"
    ):  # lane D: the words follow what the sheet shows (its mark, its page, a provisional figure)
        if provisional(line):
            return f"Contractor to confirm the provisional value of {what}{sheet_mark(line)}{' against ' + ref if ref else ''}."
        return f"Contractor to provide {what}{sheet_mark(line)}; it is deferred on the sheet."
    if case == "disagree":
        return f"Engineer to check {what}: the readers disagree."
    if case == "cut_off":
        return f"Engineer to check {what}: the second AI reader's answer was cut off, so the two readers did not agree."
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
