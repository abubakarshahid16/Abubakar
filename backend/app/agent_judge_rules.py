"""The judge's tie between a REMOVE and the ROW'S CLAIM (#1690, part of #805). Pure functions; no model, no database.

A REMOVE is the worst mistake the judge can make, so its power is NARROWED to what code can verify completely:

  * 'not_applicable' never removes a row (the judge may only note it for the engineer).
  * 'complies' removes only a NUMERIC row (a figure with a unit; clause references are read out first), and only when the
    compared pair is exactly the two REMOVE quotes, the row's OWN figure is the figure in the document quote, the code
    comparison says 'meets', and the row's subject equals the subject of both quotes.
  * 'already_stated' removes only when the document quote is `<label> <separator> <value>` with the label equal to the row's
    subject (strict equality, no superset) and a value that STARTS with a digit (a bare word is never a value).
  * the row's page comes ONLY from its page/section cell; the document quote is on that page; no cell, no REMOVE.
  * a row whose subject has fewer than MIN_SUBJECT_WORDS content words, or only generic ones, is never removed.
  * a document quote that repeats SIX or more consecutive words of the row's own comment is never a basis.
  * a quote or reason that says something is missing, omitted, pending, to be advised ... never removes (an extra net).
"""

from __future__ import annotations

import re

from . import blank_markers, claims, numparse
from .agent_subject import NEUTRAL_WORDS, _stem
from .agent_tools import NOT_MENTIONED_WORDS

MAX_SUBJECT_WORDS = 5
MIN_SUBJECT_WORDS = 2
REPEAT_RUN = 6
#: Subjects too general to tie a quote to a row: a subject made only of these words can never be removed.
GENERIC_SUBJECT_WORDS = frozenset({"data", "information", "info", "detail", "document", "documentation", "requirement", "item", "general", "note", "design", "equipment", "system", "specification", "drawing", "datum",})  # fmt: skip
#: Absence and negation words the first list does not hold. Matched as WHOLE words ("lacks" is not in "black").
ABSENCE_EXTRA = (
    "omitted", "omit", "omits", "no information", "no info", "does not state", "do not state", "did not state",
    "lacks", "lack", "lacking", "not available", "to be advised", "to be confirmed", "to be provided", "not addressed",
    "not defined", "not included", "none given", "no value", "unspecified", "unknown", "tba", "tbc", "tbd",
    "pending", "void", "empty", "nil", "none", "unavailable", "under review", "to follow", "by others", "see note",
    "in progress", "later", "not indicated", "not listed", "without value", "never issued", "no data", "not applicable",
    "awaiting", "deferred", "withheld", "not declared", "not yet available", "vendor to advise", "as per vendor",
    "to be issued", "not defined", "incomplete", "outstanding", "reserved", "tba", "by vendor", "by supplier",
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
    """The row's subject, or an EMPTY set when it cannot be used: none, more than MAX_SUBJECT_WORDS words, fewer than
    MIN_SUBJECT_WORDS, or only generic words. Such a row can never be removed."""
    found = head_subject(comment)
    if (
        not (MIN_SUBJECT_WORDS <= len(found) <= MAX_SUBJECT_WORDS)
        or found <= GENERIC_SUBJECT_WORDS
    ):
        return frozenset()
    return found


def row_pages(row: dict) -> list[int]:
    """The pages the row's PAGE/SECTION CELL names ('p. 3', 'pages 3 and 5', a bare number). A number in the comment text is
    never the row's page (it may cite the standard's page); a section number ('4.1') is not a page."""
    cell = str(row.get("page_section") or "").strip()
    pages = [
        int(n)
        for found in _PAGE_WORD.finditer(cell)
        for n in re.findall(r"\d+", found.group(1))
    ]
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


_LABEL_SEP = re.compile(r"[:=|\t]")


def label_value(quote: object) -> tuple[frozenset[str], str] | None:
    """(label subject, value text) of a quote shaped `<label><sep><value>` (sep: colon, equals, bar or tab), else None.
    The label's subject is ALL its content words (neutral words removed, inflection folded): no cutting at a function word."""
    found = _LABEL_SEP.search(str(quote or ""))
    if not found:
        return None
    label, value = str(quote)[: found.start()], str(quote)[found.end() :]
    words = {w for w in _content_words(label) if w not in NEUTRAL_WORDS}
    return (frozenset(words), value.strip()) if words else None


def digit_value(value: object) -> bool:
    """A value token: the value STARTS (after a sign or comparator) with a digit of any script. A bare word is not a value."""
    text = str(value or "").lstrip(" \t<>=~\u2264\u2265\u00b1+-\u2212")
    return bool(text) and text[0].isdecimal()


def repeats_row_text(quote: object, comment: object, run: int = REPEAT_RUN) -> bool:
    """The quote contains a run of `run` or more consecutive words of the row's own comment."""
    q, c = (
        re.findall(r"[a-z0-9]+", str(quote).lower()),
        re.findall(r"[a-z0-9]+", str(comment).lower()),
    )
    grams = {tuple(c[i : i + run]) for i in range(len(c) - run + 1)}
    return any(tuple(q[i : i + run]) in grams for i in range(len(q) - run + 1))


def own_figure_in(comment: object, doc_quote: object) -> bool:
    """One of the ROW'S OWN figures (number and unit) is a figure of the document quote."""
    mine = {
        (
            numparse.number_keys(n).__iter__().__next__()
            if numparse.number_keys(n)
            else n,
            u.rstrip(".").lower(),
        )
        for n, u in figures_in(comment)
    }
    theirs = {
        (
            numparse.number_keys(n).__iter__().__next__()
            if numparse.number_keys(n)
            else n,
            u.rstrip(".").lower(),
        )
        for n, u in figures_in(doc_quote)
    }
    return bool(mine & theirs)


def shared_subjects(rows) -> frozenset:
    """Subjects that head TWO OR MORE rows of the file: a template prefix, not a topic (it ties a quote to nothing)."""
    seen: dict = {}
    for row in rows:
        subject = row_subject(row.get("comment"))
        if subject:
            seen[subject] = seen.get(subject, 0) + 1
    return frozenset(k for k, n in seen.items() if n >= 2)


def removable_at_all(row: dict, shared: frozenset = frozenset()) -> bool:
    """The rules could ever let this row be removed: a usable subject that no other row shares, and a page/section cell
    that names a page."""
    subject = row_subject(row.get("comment"))
    return bool(subject) and subject not in shared and bool(row_pages(row))
