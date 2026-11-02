"""#1584: why a proven rule may still not stand alone, as far as word tests can see. Pure: no database, no model.

NO FLAG DOES NOT MEAN A RULE STANDS ALONE: scope named as a plain noun phrase in a heading, a parent heading, a previous
sentence holding a number and a lead-in on the prior page all stay unflagged.
"""

from __future__ import annotations

import re

from . import ai_requirements, numparse
from .compiled_rule_pages import _core, _headings, sentences_of

_CAPTION = re.compile(r"^\s*(?:table|figure|fig\.?|note)\s+\w", re.IGNORECASE)
_SCOPE_WORDS = re.compile(
    r"\b(?:only|for|appl(?:y|ies)\s+to|the\s+following)\b", re.IGNORECASE
)
_REFERS_BACK = re.compile(
    r"^\W*(?:this|these|those|such|they|it|the\s+above|the\s+foregoing|the\s+same)\b",
    re.IGNORECASE,
)
#: The next sentence takes the rule back, in part.
_NEXT_EXCEPTION = re.compile(
    r"^\W*(?:exception|exceptions|except|however|but|unless|or|alternatively|otherwise|instead|this\s+(?:\w+\s+)?does\s+not)\b"
)


def quote_span(quote: str, text: str) -> tuple[int | None, int | None]:
    """Where the quote stands in the stored page: its words, any white space between, any case."""
    pattern = r"\s+".join(re.escape(word) for word in quote.split())
    found = re.search(pattern, text, re.IGNORECASE)
    return found.span() if found else (None, None)


def _is_scope(words: str) -> bool:
    return bool(_SCOPE_WORDS.search(words)) or ai_requirements._is_conditional(words)


def _context_lines(pages: dict[int, str], page: int, start: int) -> tuple[str, str]:
    """(nearest heading above, nearest caption above): this page, then back over earlier pages for the heading."""
    before = pages[page][:start]
    here = _headings(before)
    heading = here[-1][2] if here else ""
    caption = next((x for x in reversed(before.splitlines()) if _CAPTION.match(x)), "")
    for earlier in sorted((p for p in pages if p < page), reverse=True):
        if heading:
            break
        found = _headings(pages[earlier])
        heading = found[-1][2] if found else ""
    return heading, caption


def _adjacent_scope(sentence: str, text: str) -> bool:
    """A scope in the sentence before, when it states no figure of its own, or a reference back in the one after."""
    found = sentences_of(text)
    cores = [_core(s) for s in found]
    if sentence not in cores:
        return False
    at = cores.index(sentence)
    before = found[at - 1] if at else ""
    after = found[at + 1] if at + 1 < len(found) else ""
    if before and _is_scope(before) and not numparse.find_numbers(before):
        return True
    return bool(after and _REFERS_BACK.match(after) and _is_scope(after))


def _next_is_an_exception(sentence: str, text: str) -> bool:
    found = sentences_of(text)
    cores = [_core(s) for s in found]
    if sentence not in cores:
        return False
    at = cores.index(sentence)
    return at + 1 < len(found) and bool(_NEXT_EXCEPTION.match(found[at + 1]))


def is_table_row(answer: object, tables) -> bool:
    """Does the table reader's record hold this proposal's quote? Only where a record exists."""
    if not isinstance(answer, dict) or not tables:
        return False
    return _core(str(answer.get("quote") or "")) in {
        _core(words) for words in tables.get(answer.get("page"), ())
    }


def context_flags(
    answer: dict, sentence: str, strength: str, pages, tables
) -> list[str]:
    """Why this rule may not stand alone, as far as these word tests can see. NO FLAG DOES NOT MEAN A RULE STANDS
    ALONE: scope named as a plain noun phrase in a heading, a parent heading, a previous sentence holding a number,
    an exception in the next sentence and a lead-in on the prior page all stay unflagged."""
    page, text = answer["page"], pages[answer["page"]]
    flags = []
    if is_table_row(answer, tables):
        flags.append("table_row")
    if strength == "stated":
        flags.append("row_like")
    if _REFERS_BACK.match(sentence):
        flags.append("refers_back")
    if re.search(r"\bthe\s+following\b", sentence):
        flags.append("refers_to_a_list")
    start = quote_span(" ".join(str(answer["quote"]).split()), text)[0] or 0
    heading, caption = _context_lines(pages, page, start)
    if heading and _is_scope(heading):
        flags.append("heading_scope")
    if caption and _is_scope(caption):
        flags.append("caption_scope")
    if _adjacent_scope(sentence, text):
        flags.append("adjacent_scope")
    if _next_is_an_exception(sentence, text):
        flags.append("next_sentence_exception")
    return flags
