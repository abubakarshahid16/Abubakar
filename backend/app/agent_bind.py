"""Bind a GREEN or RED finding to its item (#1690, CLAUDE.md rule 4). Pure functions: no db, no model, no network.

A GREEN or RED must be ABOUT the item it answers, not merely true of some line:
  1. every figure the finding claims (`value`, and each `figures` pair) stands INSIDE the quote it is claimed from, not
     merely somewhere on the page;
  2. the document quote shares at least TWO distinct content words with the item's topic (all of them when the topic has
     fewer than two), and the clause quote at least ONE: a title line, a header or a general note fails;
  3. a finding that fails is refused with the code `quote_not_about_item` and a fixed-word hint (no text), so the model
     can retry once with the right lines.
A YELLOW claims nothing and is never bound. The check is structural (words and numbers only; no layout, no per-sheet
words). Known cost: a true GREEN whose quote is phrased in synonyms of the topic is refused; that is the safe side, and
the reviewer can quote more lines or ask the engineer.
"""

from __future__ import annotations

import re

from . import numparse
from .agent_subject import NEUTRAL_WORDS, _stem
from .reader_api import _fold

CODE = "quote_not_about_item"
EXPECT = {
    "doc_quote": "lines that state the item's own value, sharing its topic words",
    "clause_quote": "clause lines about the same topic",
    "figures": "each figure's text must stand inside the quote it is claimed from",
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


def values_inside(finding: dict, doc_quote: str, clause_quote: str) -> bool:
    """Rule 1: the claimed value and every figures pair stand inside their quotes."""
    value = str(finding.get("value") or "").strip()
    if value and not numparse.value_in_text(value, doc_quote):
        return False
    figures = finding.get("figures")
    for fig in figures if isinstance(figures, list) else []:
        if not isinstance(fig, dict):
            return False
        if not _inside(fig.get("doc_quote"), doc_quote) or not _inside(
            fig.get("clause_quote"), clause_quote
        ):
            return False
    return True


def topic_bound(topic: str, doc_quote: str, clause_quote: str) -> bool:
    """Rule 2: the quotes share enough content words with the item's topic."""
    wanted = content_words(topic)
    if not wanted:
        return True  # nothing to bind to: a topic with no content words cannot refuse anything
    need_doc = min(MIN_DOC_WORDS, len(wanted))
    need_clause = min(MIN_CLAUSE_WORDS, len(wanted))
    return (
        len(wanted & content_words(doc_quote)) >= need_doc
        and len(wanted & content_words(clause_quote)) >= need_clause
    )


def binding_problem(finding: dict, colour: str | None, topic: str | None) -> str | None:
    """CODE when a GREEN or RED is not bound to its item, else None. YELLOW is never bound. A run with no topic known
    (no loop naming the item) binds nothing by topic; figures are still held inside their quotes."""
    if colour not in ("GREEN", "RED"):
        return None
    doc_quote, clause_quote = (
        str(finding.get("doc_quote") or ""),
        str(finding.get("clause_quote") or ""),
    )
    if not values_inside(finding, doc_quote, clause_quote):
        return CODE
    if topic is not None and not topic_bound(topic, doc_quote, clause_quote):
        return CODE
    return None
