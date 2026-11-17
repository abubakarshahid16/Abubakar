"""THE test of a quote shown as evidence on a general review's CRS (order 14 LPC, C4, 17 Nov 2026).

A quote code verified on its page proves only that the words are there. Shown as what the paper says, it must also be words a
reader can judge: "(herein referred", "4.", a run of underscores or the tail of a sentence are on the page, but they say nothing.
So an AI quote is shown as evidence only when it passes this one fixed, general test (`is_evidence`); otherwise the row says it
holds no quote and keeps the paper's words beside that mark (`refused_words`: completeness, nothing is dropped silently). Used by
every writer of a general AI line's quote: the paper's one CRS and page (`review_points_service.sentence_quotes`) and the general
review's own files (`agent_general_crs`). A value code compared (a datasheet cell, a rule check's Pass or Fail) is never read by it.

The test (general, English text; nothing of one paper's words or layout). Evidence is EITHER
  * a full sentence: it starts as a sentence starts (a capital, a digit or a quote mark; never an open bracket, a closing mark or a
    lower-case word, which is the middle of a sentence), it does not end inside an open bracket or on a word that needs more
    ("the", "of", "shall"), it holds at least `MIN_WORDS` words (a number counts as one) and a verb-like word: a modal or
    auxiliary verb ("shall", "is", "has"), a word with a verb ending ("-ed", "-es"), or, in a quote that ends as a sentence
    does, a lower-case word ending in "-s" after its first word ("The team meets ...");
  * or a one-line clause that states a value: it starts as a sentence starts, holds a number and at least two words
    ("Retention 10% of the price"), and does not end inside an open bracket.
"""

from __future__ import annotations

import re

MIN_WORDS = 6
VALUE_WORDS = 2
_TOKEN = re.compile(r"[^\W_]+(?:[.,'’-][^\W_]+)*")  # a word or a number  # noqa: RUF001
_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")  # noqa: RUF001
#: Modal and auxiliary verbs: closed-class words of English, true for any paper.
_AUX = frozenset(
    [
        "shall",
        "should",
        "will",
        "would",
        "must",
        "may",
        "might",
        "can",
        "could",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "am",
        "has",
        "have",
        "had",
        "having",
        "do",
        "does",
        "did",
    ]
)
#: Closed-class words a sentence never ends on: the words after them are missing.
_NEEDS_MORE = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "from",
        "with",
        "and",
        "or",
        "nor",
        "but",
        "as",
        "than",
        "that",
        "which",
        "who",
        "whose",
        "this",
        "these",
        "those",
        "its",
        "their",
        "shall",
        "should",
        "will",
        "would",
        "must",
        "may",
        "can",
        "could",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "has",
        "have",
        "had",
    ]
)
_VERB_ENDING = re.compile(r"^[a-z]{2,}(?:ed|es)$")
_S_ENDING = re.compile(r"^[a-z]{2,}[^s]s$")
_DIGIT = re.compile(r"\d")


def _flat(text: object) -> str:
    return " ".join(str(text or "").split())


def _starts_and_ends_whole(flat: str) -> bool:
    """It starts as a sentence starts and does not stop inside a bracket or on a word that needs more."""
    first = flat.lstrip("\"'“‘ ")[:1]  # noqa: RUF001
    if not first or first in "([{)]}" or first.islower():
        return False
    if flat.count("(") > flat.count(")") or flat.count("[") > flat.count("]"):
        return False
    words = _WORD.findall(flat)
    return not words or words[-1].lower() not in _NEEDS_MORE


def is_full_sentence(text: object) -> bool:
    """Is the quote a full sentence by the fixed test above?"""
    flat = _flat(text)
    if not _starts_and_ends_whole(flat) or len(_TOKEN.findall(flat)) < MIN_WORDS:
        return False
    words = _WORD.findall(flat)
    low = [w.lower() for w in words]
    if any(w in _AUX for w in low) or any(_VERB_ENDING.match(w) for w in low):
        return True
    ends = flat.rstrip("\"'”’ )")[-1:] in ".!?;:"  # noqa: RUF001
    return ends and any(_S_ENDING.match(w) for w in words[1:])


def is_value_clause(text: object) -> bool:
    """Is the quote a one-line clause that states a value (a number and at least two words)?"""
    flat = _flat(text)
    return (
        _starts_and_ends_whole(flat)
        and bool(_DIGIT.search(flat))
        and len(_WORD.findall(flat)) >= VALUE_WORDS
    )


def is_evidence(text: object) -> bool:
    """THE test: a full sentence, or a one-line clause that states a value."""
    return is_full_sentence(text) or is_value_clause(text)


def refused_words(text: object) -> str:
    """The mark a refused quote carries, with the paper's words beside it (never dropped)."""
    flat = _flat(text)
    if not flat:
        return "No quote: the passage found on the page is empty."
    return f'No quote: the paper\'s words "{flat}" are not a full sentence.'
