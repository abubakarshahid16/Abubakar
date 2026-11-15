"""The words around a field's name in a limit's sentence and in a paper's label (R74 B2): the QUALIFIERS the clause and the label carry, as sets, for the proof's
`qualifier_reason`. A qualifier is any word that is not the field's name, a figure, a unit or on the closed list of weak words; comparator-family words are kept apart.
Pure; no database, no model. Split out of `agent_review_code_proof` to keep that verdict-path file under its size limit."""

from __future__ import annotations

import re

from . import agent_review_absence as absence
from . import numparse

#: articles and small joining words that carry no meaning of their own (the proof's own `_BEFORE_HEAD`, kept here so this module imports nothing from the proof)
_JOIN_WORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "in",
        "at",
        "to",
        "and",
        "or",
        "that",
        "whose",
        "with",
        "no",
        "its",
        "this",
    ]
)  # "each", "any" and "all" are quantity words, not joins

#: the closed list of words a limit's sentence or a label may carry without saying anything about WHICH quantity it is: articles, the verbs and the comparator
#: phrase of the limit itself. Every other word that is not the field's name, a figure or a unit is a QUALIFIER, and the qualifiers of the clause and of the label
#: must be the same set: an unknown word on either side is a difference (a Query), never "no known conflict".
WEAK_WORDS = _JOIN_WORDS | {
    "shall", "must", "should", "will", "may", "be", "is", "are", "been", "not", "no", "exceed", "exceeds", "exceeding", "less", "more", "greater", "lower", "higher",
    "than", "least", "most", "used", "use", "value", "values", "stated", "between", "and", "to",
}  # fmt: skip
#: the comparator-family words: they qualify a LABEL ("Minimum design pressure" is not the clause's "maximum design pressure") but are the clause's own limit word
_COMPARATOR_WORDS = {
    "maximum": "maximum",
    "max": "maximum",
    "minimum": "minimum",
    "min": "minimum",
}
#: words that say which VALUE of a quantity a name means: inside a registered spelling too, they qualify (a clause's "maximum X" is not a label's "Normal X")
_BOUND_FAMILY = frozenset(
    {
        "normal",
        "rated",
        "required",
        "nominal",
        "allowable",
        "permissible",
        "actual",
    }
)
_OR_COMPARATIVE = re.compile(
    r"\bor\s+(?:more|less|higher|lower|greater|fewer|below|above|over|under)\b"
)


def is_unit_word(token: str) -> bool:
    from . import claims

    try:
        return claims.normalise("1", token).normalized_unit is not None
    except (
        ValueError,
        TypeError,
        KeyError,
    ):  # a token the unit reader cannot take is not a unit
        return False


def name_span(
    tokens: list[str], words: absence.FieldWords | None, field: str
) -> tuple[int, int] | None:
    """The token range of the field's name in the text (the longest of its registered spellings and role patterns), None when the text does not carry it whole."""
    text = " ".join(tokens)
    starts = [0]
    for t in tokens[:-1]:
        starts.append(starts[-1] + len(t) + 1)
    found: list[tuple[int, int]] = []
    names = (
        list(words.spellings)
        if words is not None
        else [" ".join(re.findall(r"[a-z0-9]+", field.lower()))]
    )  # a field the registry does not know: its own words
    for sp in names:
        for m in re.finditer(rf"(?<![a-z0-9]){re.escape(sp)}(?![a-z0-9])", text):
            found.append((m.start(), m.end()))
    if not found:  # a role pattern also absorbs prefixes ("internal", "max"): only when no registered spelling is there, so "internal" stays a qualifier
        for pat in words.patterns if words is not None else ():
            found.extend(
                (m.start(), m.end()) for m in pat.finditer(text) if m.group(0).strip()
            )
    if not found:
        return None
    lo, hi = max(found, key=lambda r: r[1] - r[0])
    covered = [i for i, st in enumerate(starts) if st < hi and st + len(tokens[i]) > lo]
    return (covered[0], covered[-1] + 1) if covered else None


def qualifier_sets(
    folded: str, words: absence.FieldWords | None, field: str
) -> tuple[set[str], set[str]] | None:
    """(qualifying words, comparator-family words) of a text around the field's name, anywhere in it; None when the text does not carry the name whole."""
    from . import requirements_3b as r3b

    folded = _OR_COMPARATIVE.sub(" ", numparse.fold(folded))
    folded = re.sub(
        r"[-+]?" + r3b._VALUE + r"\s*(?:" + r3b._UNIT + r")?(?![\w/])", " ", folded
    )  # a figure and its unit say nothing about which quantity it is
    tokens = re.findall(r"[a-z0-9]+", folded)
    span = name_span(tokens, words, field)
    if span is None:
        return None
    rest = tokens[: span[0]] + tokens[span[1] :]
    qual, comp = (
        {t for t in tokens[span[0] : span[1]] if t in _BOUND_FAMILY},
        set(),
    )  # "normal operating pressure" is a registered spelling, but "normal" still says WHICH one
    for t in rest:
        if t in _COMPARATOR_WORDS:
            comp.add(_COMPARATOR_WORDS[t])
        elif t in WEAK_WORDS or numparse.as_number(t) is not None or is_unit_word(t):
            continue
        else:
            qual.add(t)
    return qual, comp


#: words that make ANOTHER sentence of a clause more than a plain limit: a condition, an exception, an override or an alternative, a note reference, a scope word
_MORE_WORDS = re.compile(
    r"\b(?:where|if|when|unless|except|provided|apply|applies|applying|applicable|supersede|supersedes|superseded|superseding|higher|lower|relax\w*|agree|agreed|agrees|"
    r"permit|permits|permitted|waive|waived|waives|note|notes|see|refer|refers|referred|only|per|for|in\s+case)\b",
    re.IGNORECASE,
)
MORE_WHY = "the clause says more than the limit (another sentence of it carries a figure with a unit, a condition, an exception, an override or a note)"


def has_figure_with_unit(text: str) -> bool:
    """The text states a figure followed by a unit the code knows ("6 mm", "3.5 bar")."""
    from . import requirements_3b as r3b

    for m in re.finditer(
        r"[-+]?" + r3b._VALUE + r"\s*(" + r3b._UNIT + r")(?![\w/])", text or ""
    ):
        if is_unit_word(m.group(1)) or r3b.unit_token(m.group(1)):
            return True
    return False


def more_than_the_limit(sentences: list[str], limit_at: int | None) -> bool:
    """True when any sentence other than the limit's own (`limit_at`) carries a figure with a unit or one of `_MORE_WORDS`."""
    for i, sent in enumerate(sentences):
        if i == limit_at or not sent.strip():
            continue
        if has_figure_with_unit(sent) or _MORE_WORDS.search(sent):
            return True
    return False


_CLAUSE_LINE = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,3}){1,5})\.?\s+([A-Za-z(][^\n]*)$")


def _clause_key(number: str) -> tuple[int, ...] | None:
    return (
        tuple(int(x) for x in number.split("."))
        if re.fullmatch(r"\d{1,2}(?:\.\d{1,3}){0,5}", number.strip())
        else None
    )


def clause_own_text(text: object, clause: object) -> str:
    """The stored clause text cut where the clause ENDS: at the first line that starts with a clause number of the same numbering scheme that is strictly later in
    order and is not a sub-clause of this one (7.1.2.4, 7.1.3, 7.2 and 8 after 7.1.2.3; 7.1.2.3.1 is part of it), followed by a word. The stored heading structure
    reads a clause to the end of the book when a later clause is written like body text, so this is the only end that can be established; when the clause number is not
    a plain number, or no such line is found, the text is returned as it is (the proof then reads all of it: a Query, never a guess). Not a boundary: a number inside a
    sentence, a list item ("1.", "(a)": earlier in order or not a number), a line that starts with a figure and a unit ("7.5 mm"), a line that starts with a digit."""
    body, here = str(text or ""), _clause_key(str(clause or ""))
    if here is None:
        return body
    offset = 0
    for line in body.splitlines(keepends=True):
        m = _CLAUSE_LINE.match(line.rstrip("\n"))
        if m and offset:
            there = _clause_key(m.group(1))
            first_word = m.group(2).split()[0].strip("()") if m.group(2).split() else ""
            if (
                there
                and there > here
                and there[: len(here)] != here
                and not is_unit_word(first_word)
            ):
                return body[:offset]
        offset += len(line)
    return body
