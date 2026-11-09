"""Bind a GREEN or RED finding to its item (#1690, CLAUDE.md rule 4). Pure functions: no db, no model, no network.

The lead's default is YELLOW (the engineer). A GREEN or RED is accepted only when ALL of these hold:
  1. every figure it claims (`value`, each `figures` pair) stands INSIDE the quote it is claimed from, with number AND unit
     (a bare number, a date, a part-number-like token is not a figure);
  2. the clause quote is at least 40 characters and is not the clause's own heading text (or a prefix of it);
  3. the item's topic has at least two content words (fewer: YELLOW only) and the quotes share them (two with the document
     quote, one with the clause quote);
  4. EITHER a `figures` pair was DECIDED by compare_number (code, not the model),
     OR (a textual finding, no value or figures) the document quote holds EVERY topic word (at most 4), has at least 40
     characters and is not a heading-like line (6 words or fewer, no digit, no sentence punctuation).
A failure is refused as `quote_not_about_item` with a fixed-word hint (no text) that names the YELLOW way. YELLOW claims
nothing and is never bound. A run where the loop never named an item (topic None) binds nothing by topic.

LIMITS, stated plainly. This is a HEURISTIC on words and numbers; it cannot judge meaning. It does NOT bind the quote to the
right INSTANCE: a paragraph about another tag or device that uses the same words (and the same figure) passes, and so does
a figure that appears twice in a quote with different meaning. A true GREEN phrased in synonyms of the topic, or with a unit
the repo's unit table lacks, is refused (the safe side: record YELLOW). What remains behind these rules is the local second
opinion and the engineer.
"""

from __future__ import annotations

import re

from . import claims, numparse
from .agent_subject import NEUTRAL_WORDS, _stem
from .reader_api import _fold

CODE = "quote_not_about_item"
EXPECT = {
    "doc_quote": "lines that state the item's own value, sharing its topic words",
    "clause_quote": "clause lines about the same topic",
    "figures": "each figure's text must stand inside the quote it is claimed from",
    "otherwise": "record YELLOW for the engineer; an item whose topic has fewer than two content words can only be YELLOW",
}
MIN_DOC_WORDS = 2
MIN_CLAUSE_WORDS = 1
#: Words that say nothing about WHICH item a line is about (headers, notes, filler). Closed and general.
GENERIC_WORDS = frozenset(
    {
        "general", "note", "notes", "data", "sheet", "datasheet", "document", "page", "title", "table", "list", "item",
        "section", "clause", "revision", "rev", "date", "project", "client", "contractor", "design", "standard",
        "specification", "requirement", "information", "description", "detail", "refer", "reference", "per",
        "applicable", "following", "above", "below", "given", "shown", "stated", "type", "should", "may", "will",
        "with", "for", "from", "that", "this", "these", "those", "any", "all", "each", "other", "than", "such",
        "unless", "where", "when", "which", "their", "its", "has", "have", "been", "was", "were",
    }
)  # fmt: skip


def content_words(text: object) -> frozenset[str]:
    """Distinct content words of a text: lowercase letters, 3 or more, plural-folded, minus neutral and generic words."""
    out = set()
    for raw in re.findall(r"[a-z]+", str(text or "").lower()):
        word = _stem(raw)
        if len(raw) < 3 or raw in NEUTRAL_WORDS or word in NEUTRAL_WORDS:
            continue
        if raw in GENERIC_WORDS or word in GENERIC_WORDS:
            continue
        out.add(word)
    return frozenset(out)


def _inside(piece: object, quote: object) -> bool:
    text = _fold(str(piece or ""))
    return bool(text) and text in _fold(str(quote or ""))


_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"
#: Tokens whose digits are not a figure: dates (dd/mm/yyyy, yyyy-mm-dd, "May 2019") and part-number-like tokens (P-101, M12, 316L).
_NOT_FIGURE = re.compile(
    rf"\b\d{{1,4}}[/.-]\d{{1,2}}[/.-]\d{{1,4}}\b|\b(?:{_MONTHS})\.?\s+\d{{2,4}}\b|\b\d{{1,2}}\s+(?:{_MONTHS})\b\.?(?:\s+\d{{2,4}})?"
    r"|\b[A-Za-z]+[-_]?\d[\w-]*\b|\b\d+[-_][A-Za-z]\w*\b|\b\d{3,}[A-Z]\b",
    re.IGNORECASE,
)
_NUMBER_UNIT = re.compile(
    r"(?<![\w.])[-+\u2212]?\d+(?:[.,]\d+)?\s*([A-Za-z\u00b0%\u00b5\u03a9][A-Za-z\u00b0%\u00b5\u03a9/^]*)"
)
MIN_CLAUSE_QUOTE_CHARS = 40
MIN_TEXT_QUOTE_CHARS = 40
MAX_TOPIC_WORDS = 4
MAX_HEADING_WORDS = 6


def has_figure(text: object) -> bool:
    """A number WITH a unit, outside dates and part-number-like tokens. A bare number is not a figure."""
    masked = _NOT_FIGURE.sub(" ", str(text or ""))
    return any(claims.is_unit(m.group(1)) for m in _NUMBER_UNIT.finditer(masked))


def heading_like(line: str) -> bool:
    """A short line with no digit and no sentence punctuation: a heading, a title, a label."""
    return len(line.split()) <= MAX_HEADING_WORDS and not re.search(r"\d|[.;:!?]", line)


def values_inside(
    finding: dict, doc_quote: str, clause_quote: str, unit: bool = True
) -> bool:
    """Rule 1: the claimed value and every figures pair stand inside their quotes, each with number AND unit (`unit`)."""
    value = str(finding.get("value") or "").strip()
    if value and not numparse.value_in_text(value, doc_quote):
        return False
    if value and unit and not has_figure(value):
        return False
    figures = finding.get("figures")
    for fig in figures if isinstance(figures, list) else []:
        if not isinstance(fig, dict):
            return False
        if not _inside(fig.get("doc_quote"), doc_quote):
            return False  # the document side of a pair stands inside the document quote
        if not _inside(fig.get("clause_quote"), clause_quote):
            return False  # and the clause side inside the clause quote
        if unit and not (
            has_figure(fig.get("doc_quote")) and has_figure(fig.get("clause_quote"))
        ):
            return False
    return True


def decided_pair(finding: dict, decided: dict) -> bool:
    """At least one figures pair that compare_number DECIDED (by code)."""
    for fig in (
        finding.get("figures") if isinstance(finding.get("figures"), list) else []
    ):
        key = (
            str(fig.get("doc_quote") or "").strip(),
            str(fig.get("clause_quote") or "").strip(),
        )
        if (decided.get(key) or {}).get("decided") is True:
            return True
    return False


def topic_order(topic: str) -> list[str]:
    """The topic's content words in order of first appearance, at most MAX_TOPIC_WORDS."""
    seen: list[str] = []
    for raw in re.findall(r"[a-z]+", str(topic or "").lower()):
        word = next(iter(content_words(raw)), None)
        if word and word not in seen:
            seen.append(word)
    return seen[:MAX_TOPIC_WORDS]


def textual_bound(topic: str, doc_quote: str) -> bool:
    """A textual finding: the quote holds EVERY topic word (up to 4), is long enough and is not heading-like."""
    wanted = topic_order(topic)
    if len(doc_quote.strip()) < MIN_TEXT_QUOTE_CHARS or heading_like(doc_quote.strip()):
        return False
    return bool(wanted) and set(wanted) <= content_words(doc_quote)


def clause_quote_ok(clause_quote: str, clause_text: str | None) -> bool:
    """Rule 4: long enough, and not the clause's own heading text (with or without its number) or a prefix of it."""
    quote = _fold(clause_quote)
    if len(clause_quote.strip()) < MIN_CLAUSE_QUOTE_CHARS:
        return False
    heading = _fold((clause_text or "").split("\n", 1)[0])
    bare = re.sub(r"^\d[\w.()-]*\s+", "", heading)
    return not any(h and h.startswith(quote) for h in (heading, bare))


def topic_bound(topic: str, doc_quote: str, clause_quote: str) -> bool:
    """The quotes share enough content words with the item's topic (two for the document, one for the clause)."""
    wanted = content_words(
        topic
    )  # never fewer than MIN_DOC_WORDS shared, so a short topic can never bind (YELLOW only)
    return (
        len(wanted & content_words(doc_quote)) >= MIN_DOC_WORDS
        and len(wanted & content_words(clause_quote)) >= MIN_CLAUSE_WORDS
    )


def binding_problem(
    finding: dict, colour: str | None, box, clause_text: str | None = None
) -> str | None:
    """CODE when a GREEN or RED is not bound to its item, else None. YELLOW claims nothing and is never bound.

    Accepted only when: figures (if any) stand inside their quotes with number and unit; the clause quote is long enough and
    not the clause heading; the item topic has at least two content words; and EITHER a figures pair was decided by
    compare_number OR (a textual finding) the document quote holds every topic word, is long enough and is no heading.
    A run where the loop never named an item (topic None) binds nothing by topic."""
    if colour not in ("GREEN", "RED"):
        return None
    doc_quote, clause_quote = (
        str(finding.get("doc_quote") or ""),
        str(finding.get("clause_quote") or ""),
    )
    topic = box.ctx.current_topic
    if (
        topic is None
    ):  # the loop never named an item: only "figures stand inside their quotes" applies
        return (
            None
            if values_inside(finding, doc_quote, clause_quote, unit=False)
            else CODE
        )
    if not values_inside(finding, doc_quote, clause_quote):
        return CODE
    if not clause_quote_ok(clause_quote, clause_text):
        return CODE
    if not topic_bound(topic, doc_quote, clause_quote):
        return CODE  # a topic of fewer than two content words can never share two with a quote: YELLOW only
    numeric = bool(finding.get("figures")) or bool(
        str(finding.get("value") or "").strip()
    )
    if numeric:
        return None if decided_pair(finding, box._compares) else CODE
    return None if textual_bound(topic, doc_quote) else CODE
