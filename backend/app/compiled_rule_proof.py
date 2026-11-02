"""#1584: the proof of one compiled rule. The answer is a claim; these functions decide. Pure, no database, no model.

The quote must stand on the cited page's stored text; the limit and the unit inside the quote (`numparse`,
`datasheet_ai.unit_in_quote`); the comparator in the quote's own words; a scope written after the limit becomes the
rule's condition. `quote_verified` is THE quote check, run over version 1 and version 2 alike.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import claims, numparse, standards_converter
from .ai_requirement_tables import quote_on_page
from .converter_gates import fold as _fold
from .converter_gates import in_example, quote_unreadable
from .datasheet_ai import unit_in_quote

MIN_QUOTE_CHARS = 8


@dataclass
class Chunk:
    custom_id: str
    text: str
    pages: set[int] = field(default_factory=set)
    #: page -> the clauses in force on it: printed there, or running on from an earlier page.
    clauses: dict[int, set[str]] = field(default_factory=dict)


def quote_verified(quote: object, page_text: str | None) -> bool:
    """THE quote check, for version 1 and version 2 alike: the words stand on the cited page's stored text."""
    words = " ".join(str(quote or "").split())
    return (
        len(words) >= MIN_QUOTE_CHARS
        and bool(page_text)
        and quote_on_page(words, page_text)
    )


def _unit_left_out(limit: str, quote: str) -> bool:
    """A number with a recognised unit right after it in the quote, and the answer gave no unit."""
    text = numparse.fold(quote)
    wanted = numparse.as_number(limit)
    for number in numparse.find_numbers(text):
        if wanted is not None and number.value == wanted:
            after = text[number.end :].split()
            if after and claims.unit_dimension(after[0].strip(",.;:()")):
                return True
    return False


def _sentence_from(quote: str, page: str) -> str:
    """The quote and what follows it on the page, up to the sentence end or the next clause number."""
    folded, q = _fold(page), _fold(quote)
    at = folded.find(q)
    if at < 0:
        return q
    tail = re.split(
        r"[.;](?:\s|$)|\s\d+(?:\.\d+)+\s", folded[at + len(q) :], maxsplit=1
    )[0]
    return q + tail


def _scope(
    condition: str, quote: str, page: str, limit: str, unit: str
) -> tuple[str | None, bool]:
    """(condition, ok). A scope written after the limit is kept as the condition (order 289.2), so a quote cut right
    at the limit never makes a conditional rule unconditional. Two different scopes are for the engineer."""
    sentence = _sentence_from(quote, page)
    scope = standards_converter.limit_scope(sentence, quote, limit, unit) or ""
    said = _fold(condition)
    if scope and said and said not in scope and scope not in said:
        return None, False
    return (max(scope, said, key=len) or None), True


def _limit_problem(
    condition, limit, unit, comparator, quote, text
) -> tuple[str | None, str | None]:
    """(reason, condition) for a rule that states a limit."""
    if any(w in _sentence_from(quote, text) for w in standards_converter.DEFAULT_WORDS):
        return "default_not_limit", None
    if not numparse.value_in_text(limit, quote):
        return "limit_not_in_quote", None
    if unit and not unit_in_quote(unit, quote):
        return "unit_not_in_quote", None
    if not unit and _unit_left_out(limit, quote):
        return "unit_left_out", None
    if (
        comparator not in standards_converter.COMPARATORS
        or not standards_converter._comparator_says(quote, comparator)
    ):
        return "comparator_not_in_quote", None
    if not unit:
        return None, condition
    cut, ok = _scope(condition, quote, text, limit, unit)
    return (None, cut or "") if ok else ("two_conditions", None)


def _quote_problem(answer: dict, chunk: Chunk, pages: dict[int, str]) -> str | None:
    """Why a proposal's page, quote or clause is not proven, or None."""
    page = answer.get("page")
    if isinstance(page, bool) or not isinstance(page, int) or page not in chunk.pages:
        return "page_not_sent"
    text = pages.get(page, "")
    quote = " ".join(str(answer.get("quote") or "").split())
    if not quote_verified(quote, text):
        return "quote_not_on_page"
    if quote_unreadable(quote, quote):
        return "quote_unreadable"
    if in_example(
        {"requirement_text": quote, "source_text": quote, "chunk_text": text}
    ):
        return "example_not_requirement"
    clause = str(answer.get("clause") or "").strip()
    if clause.lower() in standards_converter.PLACEHOLDER_CLAUSES:
        return "no_clause"
    if clause not in chunk.clauses.get(page, set()) and not numparse.contains_whole(
        _fold(text), _fold(clause)
    ):
        return "clause_not_on_page"
    return None


def verify(
    answer: object, chunk: Chunk, pages: dict[int, str]
) -> tuple[dict | None, str | None]:
    """(rule, None) or (None, reason), for ONE proposal. Code decides; the answer is a claim."""
    if not isinstance(answer, dict):
        return None, "not_an_object"
    problem = _quote_problem(answer, chunk, pages)
    if problem:
        return None, problem
    page, text = answer["page"], pages[answer["page"]]
    quote = " ".join(str(answer.get("quote") or "").split())
    applies_to = " ".join(str(answer.get("applies_to") or "").split())
    if not applies_to:
        return None, "no_applies_to"
    name = " ".join(str(answer.get("field") or "").split())
    if not name:
        return None, "no_field"
    if not standards_converter._names_field(quote, name):
        return None, "field_not_in_quote"
    condition = " ".join(str(answer.get("condition") or "").split())
    if condition and _fold(condition) not in _fold(text):
        return None, "condition_not_on_page"
    limit = "" if answer.get("limit") is None else str(answer.get("limit")).strip()
    unit = str(answer.get("unit") or "").strip()
    comparator = str(answer.get("comparator") or "").strip()
    if limit:
        reason, condition = _limit_problem(
            condition, limit, unit, comparator, quote, text
        )
        if reason:
            return None, reason
    elif comparator or unit:
        return None, "comparator_without_limit"
    return (
        {
            "applies_to": applies_to,
            "condition_text": condition or None,
            "field": name,
            "comparator": comparator or None,
            "limit_text": limit or None,
            "limit_value": numparse.as_number(limit) if limit else None,
            "unit": unit or None,
            "unit_dimension": claims.unit_dimension(unit) if unit else None,
            "clause": str(answer.get("clause")).strip(),
            "page": page,
            "quote": quote,
        },
        None,
    )
