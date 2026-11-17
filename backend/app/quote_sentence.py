"""THE test of a quote shown as evidence on a general review's CRS (order 14 LPC, C4, 17 Nov 2026).

A quote code verified on its page proves only that the words are there. Shown as what the paper says, it must also be a sentence a
reader can judge: "(herein referred", "4.", a run of underscores or an empty line are on the page, but they say nothing. So a
quote is shown as evidence only when it is a FULL SENTENCE by this one fixed, general test; otherwise the row says it holds no
quote (`NO_SENTENCE`). Used by every writer of a general row's quote: the paper's one CRS and page (`review_points_service`), and
the general review's own files (`agent_general_crs`). A datasheet's quote (a cell value) is not read by this test.

The test (general, English text; nothing of one paper's words or layout):
  * at least `MIN_WORDS` words (a number counts as one);
  * it does not start with an open bracket or a closing mark ("(herein called");
  * it holds a verb-like word: a modal or auxiliary verb ("shall", "is", "has", ...), a word with a verb ending ("-ed", "-es"),
    or, in a quote that starts with a capital and ends as a sentence does, a lower-case word ending in "-s" after its first word
    ("The team meets ...").
"""

from __future__ import annotations

import re

MIN_WORDS = 6
NO_SENTENCE = "No quote: the passage found on the page is not a full sentence."
_TOKEN = re.compile(r"[^\W_]+(?:[.,'\u2019-][^\W_]+)*")  # a word or a number
_WORD = re.compile(r"[^\W\d_]+(?:['\u2019-][^\W\d_]+)*")
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
_VERB_ENDING = re.compile(r"^[a-z]{2,}(?:ed|es)$")
_S_ENDING = re.compile(r"^[a-z]{2,}[^s]s$")


def is_full_sentence(text: object) -> bool:
    """Is the quote a full sentence by the fixed test above?"""
    flat = " ".join(str(text or "").split())
    words = _WORD.findall(flat)
    if len(_TOKEN.findall(flat)) < MIN_WORDS:
        return False
    first = flat.lstrip("\"'\u201c\u2018 ")[:1]
    if not first or first in "([{)]}":
        return False
    low = [w.lower() for w in words]
    if any(w in _AUX for w in low) or any(_VERB_ENDING.match(w) for w in low):
        return True
    # a present-tense verb ("meets", "applies") in a sentence that ends as one: a lower-case word ending in -s after the first word
    ends = flat.rstrip("\"'\u201d\u2019 )")[-1:] in ".!?;:"
    return ends and not first.islower() and any(_S_ENDING.match(w) for w in words[1:])


def shown(text: object) -> str:
    """The quote as evidence: the text when it is a full sentence, else ""."""
    return " ".join(str(text or "").split()) if is_full_sentence(text) else ""
