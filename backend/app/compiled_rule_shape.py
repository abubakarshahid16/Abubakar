"""#1584: may a compiled rule store its figure? An ALLOW-LIST, not more words to deny. Pure: no database, no model.

A stored figure can reach a verdict. So a rule stores one only when its sentence has a shape code plainly understands:
one modal that obliges, its subject and the field on the same noun, a comparator the code knows right after the modal,
one figure with its unit right after that, and nothing else. Anything else keeps the sentence and the page, stores no
limit, and is marked `figure_not_stored` for the engineer. Losing a stored number is fine; a wrong number is not.

This never decides whether a rule is kept: a no-figure rule does not come here, and conditions are proven elsewhere.
"""

from __future__ import annotations

import re

from . import numparse
from . import standards_converter as sc
from .compiled_rule_field import _field_words
from .converter_gates import fold as _fold

FIGURE_NOT_STORED = "figure_not_stored"
_MODAL = re.compile(r"\b(?:shall|must|should|may|will)\b")
_OBLIGING_MODALS = frozenset({"shall", "must", "should"})
#: "of" is `comparators_said`'s weak cue; it never binds a figure ("pressure of a 100 mm nozzle").
_BIND_CUES = {**sc._CUES, "=": ("equal", "shall be", "must be", "is", "are", "=")}
#: Words that may stand beside the comparator between the modal and the figure and change nothing.
_FILLER = frozenset({"be", "a", "an", "the", "of", "to", "set", "have", "equal"})
#: Never plain anywhere in the sentence: another figure may be offered, or the direction may be turned round.
_NOT_PLAIN = re.compile(
    r"\b(?:or|nor|either|neither|whichever|alternatively|otherwise|cannot|prohibited|forbidden)\b|can\s+not\b"
)
_BRACKET = re.compile(r"\(([^)]*)\)")
#: A conversion ("360 psi") or a note on how a figure reads ("g", "s"): the only brackets a plain sentence holds.
_CONVERSION = re.compile(r"^\W*-?\d[\d.,/]*\s*\S{0,10}\W*$")
_READING_NOTE = re.compile(r"^\W*(?:s|es|g|a|ga|abs|absolute|gauge)\W*$")
#: In a subject, what ends the noun the rule is about: "the DIAMETER of the pipe".
_ENDS_HEAD = re.compile(
    r"\b(?:of|for|in|on|at|between|from|to|with|by|per|under|over|above|below|during)\b"
)
#: A subject with any of these is more than a noun: it has a clause, a list or a denial of its own.
_NOT_A_NOUN = re.compile(
    r",|\b(?:and|that|which|who|whose|where|when|if|is|are|was|were|be|has|have|had|not|no|never|none)\b"
)


def cue_spans(comparator: str, text: str) -> list[tuple[int, int]]:
    spans = []
    for cue in _BIND_CUES.get(comparator, ()):
        word = cue[0].isalpha()
        pattern = rf"(?<![a-z]){re.escape(cue)}(?![a-z])" if word else re.escape(cue)
        spans += [m.span() for m in re.finditer(pattern, text)]
    return spans


def _figures(text: str) -> list:
    fractions = numparse.find_fractions(text)
    inside = [(f.start, f.end) for f in fractions]
    return fractions + [
        n
        for n in numparse.find_numbers(text)
        if not any(a <= n.start < b for a, b in inside)
    ]


def _brackets_plain(text: str) -> bool:
    return all(
        _CONVERSION.match(inner) or _READING_NOTE.match(inner)
        for inner in _BRACKET.findall(text)
    )


def _subject_is_the_field(subject: str, span: str, field: str) -> bool:
    """A plain noun, and the field is on it: "the diameter of the pipe" is about a diameter, not about a pipe. A property
    named after the modal needs only the plain noun: "the wall shall have a minimum thickness of 5 mm"."""
    words = subject.strip(" ,")
    if not words or _NOT_A_NOUN.search(words):
        return False
    head = _ENDS_HEAD.split(words, maxsplit=1)[0].split()
    named = _field_words(field)
    return bool(head) and bool((_field_words(head[-1]) | _field_words(span)) & named)


def _is_named(word: str, named: set[str]) -> bool:
    """A word the field holds. A small word ("below", "at") is in no field: its emptiness proves nothing."""
    words = _field_words(word)
    return bool(words) and words <= named


def _comparator_right_after(
    span: str, subject: str, comparator: str, field: str
) -> bool:
    """Between modal and figure: the comparator's own words and nothing that changes them. "the maximum pressure shall
    be 200" has its comparator in the subject, so only the verb may stand there."""
    named = _field_words(field)

    def only_filler(words: str) -> bool:
        return all(w in _FILLER or _is_named(w, named) for w in words.split())

    if comparator == "=":
        return "be" in span.split() and only_filler(span)
    for start, stop in cue_spans(comparator, span):
        if only_filler(f"{span[:start]} {span[stop:]}"):
            return True
    return span.split() == ["be"] and bool(cue_spans(comparator, subject))


def _semicolon_beside(quote: str, page: str) -> bool:
    """A clause of the same sentence stands next to the quote: it may offer another figure, or say when this one holds."""
    folded, wanted = _fold(page), _fold(quote)
    bare = wanted.rstrip(" ;:")
    at = folded.find(bare)
    if at < 0 or wanted != bare:
        return True
    return folded[at + len(bare) :].lstrip()[:1] in {";", ":"} or folded[:at].rstrip()[
        -1:
    ] in {";", ":"}


def figure_is_plain(
    sentence: str, body: str, claim: tuple[str, str, str, str], quote: str, page: str
) -> bool:
    """May this rule store its figure? `body` is the quote outside what the rule holds as condition or exception.
    `claim`: limit, unit, comparator, field."""
    limit, unit, comparator, field = claim
    whole = numparse.fold(sentence).lower()
    modals = _MODAL.findall(whole)
    if len(modals) != 1 or modals[0] not in _OBLIGING_MODALS:
        return False
    if _NOT_PLAIN.search(whole) or not _brackets_plain(whole):
        return False
    if _semicolon_beside(quote, page):
        return False
    text = " ".join(_BRACKET.sub(" ", numparse.fold(body).lower()).split())
    figures = _figures(text)
    modal = _MODAL.search(text)
    if len(figures) != 1 or modal is None or modal.end() > figures[0].start:
        return False
    number = figures[0]
    if number.value != numparse.as_limit(limit):
        return False
    tail = text[number.end :].lstrip()
    if unit:
        wanted = numparse.fold(unit).lower()
        if not tail.startswith(wanted):
            return False
        tail = tail[len(wanted) :]
    after = (
        tail.strip(" .,;:").split()
    )  # one word may finish the property: "2 inch diameter"; more may be a scope
    if len(after) > 1 or (after and not _is_named(after[0], _field_words(field))):
        return False
    subject, span = text[: modal.start()], text[modal.end() : number.start].strip()
    return _subject_is_the_field(subject, span, field) and _comparator_right_after(
        span, subject, comparator, field
    )
