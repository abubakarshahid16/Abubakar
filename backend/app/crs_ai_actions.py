"""What the contractor is asked, and what the AI reviewer says, on a Query of the AI reviewer's CRS comment (U5, P4 and P5).

The ACTION follows what the line HOLDS about the value, decided by code and never by the reader's words (P4): a value stated on the paper
(a quote code verified) is confirmed or justified, never "stated" again; a value the sheet defers is provided, and the sentence says it is
deferred; a blank field is stated; when code cannot tell, the engineer checks and the contractor is not asked. The comment's second line
carries the AI reviewer's own reasoning, labelled as its view (P5); a proven Pass or Fail has none. No model, no network."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import NamedTuple

from . import agent_review_crosscheck as crosscheck
from . import agent_review_two_reader as two
from . import crs_ai_words as words
from .agent_review_verdict import SILENCE_CODES, quote_defers

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
    if two.disagrees(line) or two.absence_disagrees(line) or crosscheck.disagrees(line):
        return "disagree"  # opposite verdicts (two readers, or the second AI of another company): code's own flag
    verified = bool(verified_quote(line))
    if line.get("reason_code") == "value_deferred":
        return "deferred"
    if verified and quote_defers(line.get("paper_quote")):
        return "deferred"
    # FTU-1: the line's OWN reason says the paper does not state it: a found quote that may state it is the engineer's to check (the
    # reader contradicts itself); otherwise the contractor states the value
    if silent_quote(line) == CONTRADICTS:
        return "contradicts"
    if says_silent(line):
        return "blank"
    if verified:
        return "stated"
    return "unknown"


def verified_quote(line: Mapping) -> str:
    """The line's paper quote when code found it on the page, else ""."""
    checked = (line.get("quotes_checked") or {}).get("paper")
    return " ".join(str(line.get("paper_quote") or "").split()) if checked else ""


def says_silent(line: Mapping) -> bool:
    """The line's OWN record says the paper does not state the value: a silence reason code, the silence query flag or the word
    "not stated" (never the reader's free words)."""
    return (
        line.get("reason_code") in SILENCE_CODES
        or bool(line.get("silence_query"))
        or line.get("verdict_label") == two.WORD_NOT_STATED
    )


LOOKED, CONTRADICTS = "looked", "contradicts"

#: FTU-1: the reason of a silent row whose found quote is the field's own label alone (code can show it holds no value)
NOT_STATED_REASON = (
    "the paper does not state this value (the reader's reading, not proven by code); "
    "the words it quoted are where it looked, not evidence of a value"
)
#: FTU-1: the reason of a silent row whose found quote is anything else: it may state the value, code decides neither way
CONTRADICT_REASON = (
    "the reader says the paper does not state this value, but the words it quoted are on the page and may state it; "
    "code did not decide which is right, so the engineer checks"
)


class SilentRow(NamedTuple):
    """Every wording cell of ONE silent row, decided together: its kind, Reason, action, the paper cell (note) and the quote's check cell."""

    kind: str
    reason: str
    action: str
    note: str
    check: str


def whole_label(quote: str, labels) -> bool:
    """The quote is exactly one of the field's labels: ALL of that label's words and nothing else, and no figure (stemmed words, the
    same stemmer as `agent_review_verdict.quote_is_label_only`, which stays the met guard's wider test)."""
    from .agent_bind import _stem

    def stems(text: object) -> set[str]:
        return {
            _stem(w)
            for w in re.findall(r"[a-z]+", str(text or "").replace("_", " ").lower())
        }

    have = stems(quote)
    return (
        bool(have)
        and not re.search(r"\d", quote)
        and any(have == stems(lab) for lab in labels if lab)
    )


def found_quote_kind(quote: str, labels) -> str:
    """`LOOKED` only when code can show the found quote holds no value (`whole_label`); `CONTRADICTS` for every other quote."""
    return LOOKED if whole_label(quote, labels) else CONTRADICTS


#: FTU-1: the reason of a two-reader "not stated" whose found quote is the field's own label alone: the verdict stands, said as it is
AGREED_NOT_STATED_REASON = (
    "two AI readers each read every page and found no value, and the code searched the pages and found none; "
    "the words quoted are the field's own label, not a value"
)


def silent_row_words(
    field: str, quote: str, labels=(), where: str = "", agreed: bool = False
) -> SilentRow:
    """FTU-1: THE ONE decision of a silent row (its own record says the paper gives no value) that carries a quote code found on the
    page: the kind (`found_quote_kind`) and every wording cell with it, so the cells of one row can never disagree. Read by the AI
    review's lines (`silent_row`: the points, both sheets, the reason) and the rule check's points (`review_points.rule_point`)."""
    what = field or "the value asked for"
    if found_quote_kind(quote, [field, *labels]) == LOOKED:
        return SilentRow(
            LOOKED,
            AGREED_NOT_STATED_REASON if agreed else NOT_STATED_REASON,
            f"Contractor to state {what}, or the page where it is shown.",
            f'Not evidence of a value: the reader says the paper does not state it, and looked here: "{quote}"{where} '
            "(found on the page by code).",
            "where the reader looked, not evidence of a value",
        )
    return SilentRow(
        CONTRADICTS,
        CONTRADICT_REASON,
        f"Engineer to check {what}: the reader says it is not stated, but quoted words from the page that may state it.",
        f'The reader says the paper does not state it, but quoted: "{quote}"{where} (found on the page by code), which may '
        "state it; code did not decide which is right, so the engineer checks.",
        "may state it; the engineer checks",
    )


def silent_row(line: Mapping, what: str = "", where: str = "") -> SilentRow | None:
    """`silent_row_words` of an AI line whose own record says the paper does not state the value (`says_silent`) and whose quote code
    found on the page does not defer the value (a deferral is read as one); None for any other line, and None for a line code
    proved (a Pass or Fail decided by code: its proof words are its own, `absence_proof`, and the reader's quote is not its evidence).
    A two-reader "not stated" (`agent_review_two_reader.absence_agrees`) keeps its verdict only on a label-alone quote, said so."""
    from .agent_review_crs import field_words

    quote = verified_quote(line)
    if not quote or not says_silent(line) or quote_defers(quote) or proven(line):
        return None
    # R2-1854: the second AI disagreed: the engineer's question, worded by `query_action` (one home)
    if crosscheck.disagrees(line):
        return None
    labels = (
        line.get("field_label_ai"),
        line.get("field"),
        *(line.get("field_roles") or []),
    )
    agreed = two.absence_agrees(line)
    return silent_row_words(what or field_words(line), quote, labels, where, agreed)


def proven(line: Mapping) -> bool:
    """A Pass or Fail decided by code (the stored verdict; `agent_review_wording.classify` step 4 calls it proven)."""
    return line.get("verdict") in ("Pass", "Fail")


def absence_proof(line: Mapping) -> str:
    """FTU-1: the reason of a Fail code proved by its own search of every page (decided by absence); "" for any other line."""
    from .agent_review_crs import field_words
    from .agent_review_verdict import BY_ABSENCE, FAIL

    if line.get("verdict") != FAIL or line.get("decided_by") != BY_ABSENCE:
        return ""
    pages = ", ".join(str(p) for p in line.get("pages_searched") or [])
    return (
        f"code searched every page for {field_words(line) or 'the value asked for'} and found no value"
        + (f" (pages searched: {pages})" if pages else "")
    )


def silent_quote(line: Mapping) -> str:
    row = silent_row(line)
    return row.kind if row else ""


def looked_only(line: Mapping) -> bool:
    return silent_quote(line) == LOOKED


def quote_words(line: Mapping, where: str = "") -> str:
    """The paper cell a sheet adds for a silent row ("" for any other line): `silent_row`'s note."""
    row = silent_row(line, where=where)
    return f" {row.note}" if row else ""


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


def reason_for(line: Mapping, why: str) -> str:
    """The reason shown with a line, made to agree with the line's OWN reason code (FTU-1): a line that says the paper does not state the
    value says so when code can show its found quote is no value (`LOOKED`); when the quote may state it, neutral words (`CONTRADICTS`);
    otherwise the stored reason in plain words."""
    if proof := absence_proof(line):  # FTU-1: a code-proved absence says its proof
        return proof
    row = silent_row(line)
    return row.reason if row else why


def query_action(line: Mapping, what: str, ref: str) -> str:
    """Part 3 of a Query: the sentence for the case the line is in."""
    if row := silent_row(
        line, what
    ):  # FTU-1: a silent row's action is decided with its other cells
        return row.action
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
