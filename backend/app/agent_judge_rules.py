"""The judge's tie between a REMOVE and the ROW'S CLAIM (#1690, part of #805). Pure functions; no model, no database.

A REMOVE is the worst mistake the judge can make, so its quotes must be about THE ROW'S subject, on THE ROW'S page:

  row_subject      the head noun phrase of the row's comment (the content words before its first digit, colon or function
                   word), with the inflection folding and the closed neutral-word set of `agent_subject`. Empty or longer than
                   MAX_SUBJECT_WORDS: not derivable, and a row whose subject is not derivable can never be removed.
  head_subject     the same reading of a QUOTE. 'complies' needs row == document quote == clause quote, strictly.
  row_pages        the pages the row names; none named: the page must contain the subject words (checked by code).
  absence          a quote or reason that says something is missing, omitted, not provided, to be advised, blank ...: never
                   a basis for a REMOVE (`agent_tools.NOT_MENTIONED_WORDS`, extended, and `blank_markers`, whole words).
  value_like       'already_stated' needs the document quote to carry a value: a digit, a unit, or a non-blank entry.
  numeric_row      a comment that holds a FIGURE WITH A UNIT; clause references and dotted numbers are read out first.
  scope_heading    'not_applicable' needs the clause quote to lie in the clause's own scope or applicability clause.
"""

from __future__ import annotations

import re

from . import blank_markers, claims, numparse
from .agent_subject import NEUTRAL_WORDS, _stem
from .agent_tools import NOT_MENTIONED_WORDS

MAX_SUBJECT_WORDS = 5
#: Absence and negation words the first list does not hold. Matched as WHOLE words ("lacks" is not in "black").
ABSENCE_EXTRA = (
    "omitted", "omit", "omits", "no information", "no info", "does not state", "do not state", "did not state",
    "lacks", "lack", "lacking", "not available", "to be advised", "to be confirmed", "to be provided", "not addressed",
    "not defined", "not included", "none given", "no value", "unspecified", "unknown", "tba", "tbc", "tbd",
)  # fmt: skip
_ABSENCE = re.compile(
    r"(?<![a-z0-9])(?:"
    + "|".join(
        re.escape(w).replace(r"\ ", r"\s+")
        for w in (*NOT_MENTIONED_WORDS, *ABSENCE_EXTRA)
    )
    + r")(?![a-z0-9])",
    re.IGNORECASE,
)
_CUT = re.compile(r"[0-9:=(;\[]")
_CLAUSE_REF = re.compile(
    r"\b(?:clause|cl\.|section|sec\.|para(?:graph)?\.?|item|table|figure|fig\.|page|pages|p\.|pp\.|annex|appendix)\s*[a-z]?\d+(?:\.\d+)*[a-z]?",
    re.IGNORECASE,
)
_DOTTED = re.compile(r"\b\d+(?:\.\d+){2,}\b")
_FIGURE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([A-Za-z%°/][A-Za-z0-9%°/.²³]*)")
_PAGE_WORD = re.compile(
    r"\b(?:pages?|pp?\.?)\s*(\d+(?:\s*(?:,|and|&)\s*\d+)*)", re.IGNORECASE
)
_SCOPE_WORD = re.compile(
    r"\b(?:scope|applicab\w*|application|field of application)\b", re.IGNORECASE
)
#: Words that name no particular equipment or kind: sharing only these proves nothing about a kind.
GENERIC_KIND_WORDS = frozenset({"equipment", "document", "system", "item", "unit", "clause", "standard", "this", "that", "these", "those", "does", "apply", "applies"})  # fmt: skip


def _content_words(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z]+", str(text).lower())]


def head_subject(text: object) -> frozenset[str]:
    """The content words at the head of `text`, before its first digit, colon, '=', bracket, semicolon or function word."""
    head = _CUT.split(str(text or ""))[0]
    out: list[str] = []
    for raw in re.findall(r"[a-z]+", head.lower()):
        word = _stem(raw)
        neutral = raw in NEUTRAL_WORDS or word in NEUTRAL_WORDS
        if neutral and not out:
            continue  # leading articles and the like
        if neutral:
            break
        out.append(word)
    return frozenset(out)


def row_subject(comment: object) -> frozenset[str]:
    """The row's subject, or an EMPTY set when it cannot be derived (none, or more than MAX_SUBJECT_WORDS words)."""
    found = head_subject(comment)
    return found if 0 < len(found) <= MAX_SUBJECT_WORDS else frozenset()


def row_pages(row: dict) -> list[int]:
    """The pages the row names: its page cell and its comment ('p. 3', 'page 3', 'pages 3 and 4', a bare number cell)."""
    pages: list[int] = []
    cell = str(row.get("page_section") or "").strip()
    texts = [cell, str(row.get("comment") or "")]
    for text in texts:
        for found in _PAGE_WORD.finditer(text):
            pages += [int(n) for n in re.findall(r"\d+", found.group(1))]
    if cell.isdigit():
        pages.append(int(cell))
    return list(dict.fromkeys(pages))


def words_in(text: object, words: frozenset[str]) -> bool:
    return words <= set(_content_words(str(text)))


def absence(text: object) -> bool:
    """The text says something is missing, omitted, not provided, to be advised or blank (never a basis for a REMOVE)."""
    return bool(_ABSENCE.search(str(text or ""))) or blank_markers.names_a_marker(
        str(text or "")
    )


def value_like(quote: object) -> bool:
    """The quote carries a value: a digit, a unit, or a non-blank entry after its label."""
    text = str(quote or "")
    if any(ch.isdigit() for ch in text) or any(
        claims.is_unit(w) for w in re.findall(r"[A-Za-z%]+", text) if len(w) > 1
    ):
        return True
    entry = text.split(":", 1)[1].strip() if ":" in text else ""
    return bool(entry) and not blank_markers.is_marker(entry)


def figures_in(comment: object) -> list[tuple[str, str]]:
    """(number, unit) pairs in the comment, after clause references and dotted numbers ('4.1.4.4') are read out."""
    text = _DOTTED.sub(" ", _CLAUSE_REF.sub(" ", str(comment or "")))
    return [(n, u) for n, u in _FIGURE.findall(text) if claims.is_unit(u.rstrip("."))]


def row_numbers(comment: object) -> set:
    """The number keys of the row's own figures."""
    return (
        set().union(*(numparse.number_keys(n) for n, _u in figures_in(comment)))
        if figures_in(comment)
        else set()
    )


def numeric_row(comment: object) -> bool:
    return bool(figures_in(comment))


def scope_heading(clause_body: str) -> bool:
    """The clause is a scope or applicability clause: its own heading line says so."""
    first = next((ln for ln in str(clause_body).splitlines() if ln.strip()), "")
    return bool(_SCOPE_WORD.search(first))


def kind_overlap(doc_quote: object, clause_quote: object) -> bool:
    """The document quote names the equipment or kind the clause quote speaks of: they share a non-generic content word."""
    shared = set(_content_words(str(doc_quote))) & set(
        _content_words(str(clause_quote))
    )
    return bool(shared - GENERIC_KIND_WORDS - NEUTRAL_WORDS)
