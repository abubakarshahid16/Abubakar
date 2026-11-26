"""THE FIELD-LABEL RULE OF CHAT'S ANSWER GATE (lead-4, 26 Nov 2026, G7 (3); measured before it was built).

The semantic half of the gate (`answer._is_semantically_credible`) refuses a passage whose re-rank score is under
`answer.MIN_RERANK_SCORE`. A datasheet's table passages are long rows of cells, and the re-ranker scores them low even when they
hold the very field asked: on a practice copy of live, "What is the operating pressure?" on a datasheet whose passage holds that
label was refused at -4.5. Measured on 10 field questions on 3 datasheets (each answer checked on its page): the current gate
answered 4 right, 2 wrong and refused 4; letting a passage through when it holds the question's field label VERBATIM answered
7 right, 2 wrong and refused 1 (the 2 wrong are the same under both: a nearby note quoted instead of the value).

So a passage also passes the semantic half when it holds, word for word, every content word of the question in the question's
own order, two words at least (a one-word label such as "viscosity" is too common to vouch for a passage). Only Chat's answer
path asks this gate; reviews never do. Code only, no model."""

from __future__ import annotations

import re

#: Words of a question that are not part of a field's label.
_NOT_LABEL = frozenset(
    re.findall(
        r"[a-z]+",
        "what whats which is are was were the a an of for please tell me give show state stated does do did its it this that "
        "these those paper papers datasheet datasheets document documents sheet in on from s value values",
    )
)
#: A label needs at least this many words to vouch for a passage.
MIN_WORDS = 2


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", str(text or "").lower())


def label_of(question: str) -> str | None:
    """The question's field label (its content words in order), or None when it has fewer than `MIN_WORDS`."""
    words = [w for w in _words(question) if w not in _NOT_LABEL]
    return " ".join(words) if len(words) >= MIN_WORDS else None


def vouches(hit: dict, question: str | None) -> bool:
    """True when the passage holds the question's field label word for word (`label_of`)."""
    label = label_of(question or "")
    if not label:
        return False
    return f" {label} " in f" {' '.join(_words(hit.get('text')))} "


#: Words that make a passage a NOTE about a field ("shall be calculated", "as per the MSD") rather than its value.
_NOTE_WORDS = re.compile(
    r"\b(?:shall|should|must|as per|refer|see note|to be|by others)\b", re.I
)
#: How far after the label its value may sit (a table row's next cells).
VALUE_WITHIN = 80


def states_value(hit: dict, question: str | None) -> bool:
    """True when the passage holds the question's field label followed, within `VALUE_WITHIN` characters and before any note word,
    by a figure (the field's value as a datasheet row gives it)."""
    label = label_of(question or "")
    if not label:
        return False
    text = " ".join(str(hit.get("text") or "").split())
    pattern = r"\W+".join(re.escape(w) for w in label.split())
    for m in re.finditer(pattern, text, re.I):
        after = text[m.end() : m.end() + VALUE_WITHIN]
        note = _NOTE_WORDS.search(after)
        figure = re.search(r"\d", after)
        if figure and (note is None or figure.start() < note.start()):
            return True
    return False


def stated_first(
    question: str, hits: list[dict], index: int, plausible, window: int
) -> int:
    """The passage to quote for a field question: `index` (the gate's own pick) unless that passage holds the field's label but
    states no value (a note about the field), and a later candidate within `window` that is lexically `plausible` states it."""
    if not hits or index >= len(hits) or label_of(question) is None:
        return index
    lead = hits[index]
    if states_value(lead, question) or not vouches(lead, question):
        return index
    for i, hit in enumerate(hits[:window]):
        if i != index and states_value(hit, question) and plausible(hit):
            return i
    return index
