"""Two guards on a textual Pass (a rule WITHOUT numbers), order 13, W2 finding of 12 Nov 2026. Pure functions, no I/O, no model call.

A textual Pass was "proven by code" when the AI's paper quote stands on the page, its clause quote stands in the clause and is long
enough, and a second reader agrees. Code compared no value and did not check that the quote answers the rule's own FIELD or the
rule's CONDITION. A guard here can only take a Pass away: the line becomes a Query that the exit words "AI thinks: met" (never a
Pass), with a plain reason that states only what the code saw and one reason code. A Fail, a number rule (code compares the
figures) and every other decision pass through untouched.

A. FIELD (`belongs`): the verified paper quote must stand on a page LINE, or next to one (`LINE_RADIUS`), that carries the words of the rule's field. The rule's field
   is the label's field and the item's field roles (`agent_review_absence.field_words`: the registry's label patterns and
   spellings; a field the registry does not know falls back to the content words of its name). The AI's own field label is never
   evidence. A field that is not known, or words the quote's line does not carry: not a Pass.
B. CONDITION (`conditional` + a verified `condition_quote`): when the verified clause quote or the rule's stored requirement holds a
   condition (`agent_review_verdict.is_conditional`, one home), a Pass needs a verified paper quote for the condition too; the answer
   carries it as `condition_quote` and `condition_page` (empty: no Pass).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import agent_bind
from . import agent_review_absence as absence
from . import agent_review_verdict as verdict
from .reader_api import _fold

CODE_FIELD_UNKNOWN = "pass_field_unknown"
CODE_FIELD_NOT_QUOTED = "pass_field_not_quoted"
CODE_CONDITION_NOT_QUOTED = "pass_condition_not_quoted"
#: the lines on each side of the quote's own lines that may carry the field's label (a label above or below its value)
LINE_RADIUS = 1
CODES = (CODE_FIELD_UNKNOWN, CODE_FIELD_NOT_QUOTED, CODE_CONDITION_NOT_QUOTED)
FIELD_UNKNOWN_WHY = (
    "the code cannot tell which field the quoted line is: the rule's field is not known"
)
FIELD_LINE_WHY = "the quoted line is not the {field} line"
CONDITION_NOT_QUOTED_WHY = (
    "the AI reviewer holds no verified quote for the condition the rule applies under"
)


def field_names(item: Mapping) -> list[str]:
    """The rule's own field names: the label's field, then the item's field roles."""
    label = (
        item.get("rule_label") if isinstance(item.get("rule_label"), Mapping) else {}
    )
    names = [
        str(label.get("field") or "").strip(),
        *[str(r).strip() for r in item.get("field_roles") or []],
    ]
    return [n for n in dict.fromkeys(names) if n]


def quote_lines(page_text: Any, quote: Any, radius: int = 0) -> list[str]:
    """The (folded) page lines the verified quote lies on, or across, and `radius` lines on each side of them (a table read out line
    by line puts a label and its value on neighbouring lines). [] when the quote is not on the page."""
    q = _fold(str(quote or "")).strip()
    pieces, pos = [], 0
    for raw in str(page_text or "").splitlines():
        folded = _fold(raw)
        if folded:
            pieces.append((pos, pos + len(folded), folded))
            pos += (
                len(folded) + 1
            )  # one space between folded lines, as `_fold` joins them
    i = " ".join(p[2] for p in pieces).find(q) if q else -1
    if i < 0:
        return []
    hit = [k for k, (a, b, _f) in enumerate(pieces) if a < i + len(q) and i < b]
    lo, hi = max(0, min(hit) - radius), min(len(pieces) - 1, max(hit) + radius)
    return [pieces[k][2] for k in range(lo, hi + 1)]


def _carries(line: str, names: list[str]) -> bool:
    words = absence.field_words([(n, "rule label") for n in names])
    if words is not None:
        return absence._line_has(line, words, any_word=True)
    want = agent_bind.content_words(" ".join(n.replace("_", " ") for n in names))
    return bool(want & agent_bind.content_words(line))


def belongs(
    item: Mapping, quote: Any, page_text: Any
) -> tuple[bool, str | None, str | None]:
    """(ok, reason code, reason): the strict test of guard A. Not established = not ok, with the reason in plain words."""
    names = field_names(item)
    if not names:
        return False, CODE_FIELD_UNKNOWN, FIELD_UNKNOWN_WHY
    if any(
        _carries(line, names) for line in quote_lines(page_text, quote, LINE_RADIUS)
    ):
        return True, None, None
    return (
        False,
        CODE_FIELD_NOT_QUOTED,
        FIELD_LINE_WHY.format(field=names[0].replace("_", " ")),
    )


def check(
    item: Mapping, answer: Mapping, pages: Mapping[int, str], requirement: str | None
) -> tuple[str, str] | None:
    """(reason code, reason) when a textual Pass of a rule without numbers must not stand, else None. Call only for a Pass."""
    if verdict.is_number_item(item):
        return None
    page = verdict._page_no(answer.get("paper_page"))
    ok, code, why = belongs(
        item, answer.get("paper_quote"), pages.get(page) if page else None
    )
    if not ok:
        return str(code), str(why)
    if verdict.is_conditional(answer.get("clause_quote"), requirement):
        cond, _why = verdict.check_paper_quote(
            answer.get("condition_quote"), answer.get("condition_page"), pages
        )
        if not cond:
            return CODE_CONDITION_NOT_QUOTED, CONDITION_NOT_QUOTED_WHY
    return None
