"""Coverage of numeric requirements by compiled rules (Lane 1 b), for any standard.

A numeric requirement sentence is one that holds an obligation word (shall, must, required) AND a figure: a number with a
unit of the repo's unit table, read by `numparse` and `claims` (no second number reader). It is COVERED when a compiled
rule's quote of the same page overlaps it (offsets in the folded page; a sentence or quote not located there covers nothing, so it counts uncovered); otherwise it
is UNCOVERED, a candidate for a later compile step. Pure: no database, no model. Sentence text is returned so the local
coverage file can feed that step; callers must never print it.
"""

from __future__ import annotations

import re

from . import rule_finish_figures as ff
from .compiled_rule_pages import _clause_in_force, sentences_of
from .converter_gates import fold as _fold

_OBLIGATION = re.compile(r"\b(?:shall|must|required)\b")


def is_numeric_requirement(sentence: str) -> bool:
    return bool(_OBLIGATION.search(sentence.lower())) and bool(ff.figures(sentence))


def _span(needle: str, folded_page: str) -> tuple[int, int] | None:
    at = folded_page.find(needle) if needle else -1
    return (at, at + len(needle)) if at >= 0 else None


def numeric_clause_coverage(standard_pages: dict[int, str], rules: list[dict]) -> dict:
    """{"numeric": n, "covered": c, "uncovered": u, "items": [{page, clause, offset, covered, sentence}]} for the
    numeric requirement sentences of `standard_pages` ({page: text}) against `rules` (dicts with `page` and `quote`)."""
    by_page: dict[int, list[str]] = {}
    for rule in rules:
        quote = _fold(rule.get("quote") or "")
        if quote and rule.get("page") is not None:
            by_page.setdefault(rule["page"], []).append(quote)
    items = []
    for page in sorted(standard_pages):
        text = standard_pages[page] or ""
        folded_page = _fold(text)
        quotes = by_page.get(page, [])
        quote_spans = [
            (q, _span(q, folded_page)) for q in quotes
        ]  # a quote not found on the page covers nothing
        for sentence in sentences_of(text):
            if not is_numeric_requirement(sentence):
                continue
            span = _span(sentence, folded_page)
            covered = False
            for _quote, quote_span in quote_spans:
                covered = bool(
                    span
                    and quote_span
                    and span[0] < quote_span[1]
                    and quote_span[0] < span[1]
                )
                if covered:
                    break
            items.append(
                {
                    "page": page,
                    "clause": _clause_in_force(
                        standard_pages, page, span[0] if span else 0
                    ),
                    "offset": span[0] if span else None,
                    "covered": covered,
                    "sentence": sentence,
                }
            )
    covered_n = sum(1 for i in items if i["covered"])
    return {
        "numeric": len(items),
        "covered": covered_n,
        "uncovered": len(items) - covered_n,
        "items": items,
    }
