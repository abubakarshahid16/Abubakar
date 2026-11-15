"""THE STRICT LOCK of the Writer's wording (owner: "code checks it changed no fact"): a wording is kept only when it keeps the MEANING of the code's
words, from fixed lists in code (no per-paper word list). `crs_wording.lock` guards numbers, units, clause numbers and standards; this adds the
words that carry a requirement's meaning, for EVERY kind of row:

  modal words        shall, must, should, may, can, will, is to, are to
  polarity           not, no, never, without, none, neither, nor, and the un- / non- forms of one stem
  bounds, direction  minimum, maximum, at least, at most, not less than, not more than, below, above, under, over, less, greater, more, fewer,
                     before, after, within, exceed, up to
  quantity           all, each, every, any, only, either, both
  conditions         if, unless, when, where, provided, except, subject to: the same count, and the words right after each one kept
  status             met, not met, pass, fail, complies, does not comply, missing, stated, deferred

The MULTISET of these words is identical in the code's words and in the wording; no new tag or document name appears; every field name and tag of
the code's words is present; and the wording's length stays within a band (a wording that dropped half the words dropped a condition). A refused
wording gives its reason; the code's words stay. Pure; no model, no network.
"""

from __future__ import annotations

import re
from collections import Counter

PHRASES = (
    "not less than", "not more than", "does not comply", "subject to", "at least", "at most", "up to", "not met", "is to", "are to",
)  # fmt: skip
MODAL = ("shall", "must", "should", "may", "can", "will", "is_to", "are_to")
POLARITY = ("not", "no", "never", "without", "none", "neither", "nor")
BOUNDS = (
    "minimum", "maximum", "at_least", "at_most", "not_less_than", "not_more_than", "below", "above", "under", "over", "less", "greater",
    "more", "fewer", "before", "after", "within", "exceed", "exceeds", "exceeded", "up_to",
)  # fmt: skip
QUANTITY = ("all", "each", "every", "any", "only", "either", "both")
CONDITION = ("if", "unless", "when", "where", "provided", "except", "subject_to")
STATUS = (
    "met", "not_met", "pass", "fail", "complies", "comply", "meets", "meet", "does_not_comply", "missing", "stated", "deferred",
)  # fmt: skip
MEANING = frozenset(MODAL + POLARITY + BOUNDS + QUANTITY + CONDITION + STATUS)
_NEG_FORM = re.compile(r"^(?:un|non)-?[a-z]{3,}$")
_WORD = re.compile(r"[a-z0-9_][a-z0-9_\-/.]*")
_TAGGY = re.compile(
    r"^(?=.*\d)(?=.*[a-z])[a-z0-9]+(?:[-/.][a-z0-9]+)+$"
)  # a tag or an id shape: letters and digits joined by - / .
BAND_LOW, BAND_HIGH = 0.6, 1.6

MODAL_CHANGED = "modal_word_changed"
POLARITY_CHANGED = "polarity_changed"
BOUND_CHANGED = "bound_or_direction_changed"
QUANTITY_CHANGED = "quantity_word_changed"
CONDITION_CHANGED = "condition_changed"
STATUS_CHANGED = "status_word_changed"
TAG_ADDED = "tag_or_name_added"
FIELD_DROPPED = "field_or_tag_dropped"
LENGTH_BAND = "length_outside_band"
_CATEGORY_REASON = (
    (MODAL, MODAL_CHANGED), (POLARITY, POLARITY_CHANGED), (BOUNDS, BOUND_CHANGED), (QUANTITY, QUANTITY_CHANGED),
    (CONDITION, CONDITION_CHANGED), (STATUS, STATUS_CHANGED),
)  # fmt: skip


def _tokens(text: str) -> list[str]:
    t = " " + " ".join(str(text or "").lower().replace(chr(0x2011), "-").split()) + " "
    for phrase in PHRASES:
        t = t.replace(f" {phrase} ", " " + phrase.replace(" ", "_") + " ")
    t = re.sub(r"[,;:()\[\]\"']", " ", t)
    return [w.strip(".") for w in _WORD.findall(t) if w.strip(".")]


def _meaning(tokens: list[str]) -> Counter:
    c: Counter = Counter()
    for w in tokens:
        if w in MEANING:
            c[w] += 1
        elif _NEG_FORM.match(w):
            c["un-form"] += (
                1  # an un- / non- form is a polarity word: one stem more or less changes a meaning
            )
    return c


def _after_conditions(tokens: list[str]) -> Counter:
    """For each condition marker, the six words right after it (they are the condition)."""
    out: Counter = Counter()
    for i, w in enumerate(tokens):
        if w in CONDITION:
            out[(w, tuple(tokens[i + 1 : i + 7]))] += 1
    return out


def refusal(code_text: str, wording: str, must_have=()) -> str | None:
    """None when `wording` keeps every fact of `code_text`; else the reason code. `must_have`: field names and tags the wording must still say."""
    a, b = _tokens(code_text), _tokens(wording)
    ma, mb = _meaning(a), _meaning(b)
    for words, reason in _CATEGORY_REASON:
        if any(ma[w] != mb[w] for w in words):
            return reason
    if ma["un-form"] != mb["un-form"]:
        return POLARITY_CHANGED
    if _after_conditions(a) != _after_conditions(b):
        return CONDITION_CHANGED
    tags_a = {w for w in a if _TAGGY.match(w)}
    if {w for w in b if _TAGGY.match(w)} - tags_a:
        return TAG_ADDED
    if any(w not in b for w in tags_a):
        return FIELD_DROPPED
    for name in must_have:
        words = [w for w in _tokens(name) if w not in MEANING]
        if words and not all(w in b for w in words):
            return FIELD_DROPPED
    if a and not (BAND_LOW * len(a) <= len(b) <= BAND_HIGH * len(a)):
        return LENGTH_BAND
    return None
