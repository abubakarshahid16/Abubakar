"""Rule 7 of the pairing rules: a requirement pairs with a datasheet field only if its SUBJECT is the same quantity.

Owner order 3 Nov 2026 (priority 1, from a live review). Containment and the AI matcher paired a coating thickness
limit with the sheet's corrosion allowance, and a window's design life with the vessel's design life: every word of
the field was in the sentence, and the quantity was not the same.

THE RULE (general: no spelling, standard or layout is named here). Both sides are reduced to the words that say WHICH
quantity they are: the phrase in its canonical spelling (`field_links.canonical`, the closed synonym table), minus
numbers, tags and units (the unit table), minus the neutral and bound words (a, the, of, minimum, maximum, shall,
exceed ...: the rest of the checks handle which bound), minus the words naming the sheet's own kind of equipment ("the design pressure of the
vessel" is the sheet's design pressure). The two sets must be EQUAL:
  * different quantity (coating thickness against corrosion allowance; the design life of a window against the design
    life; MAWP against design pressure): refused;
  * a requirement with NO subject: refused, never paired by the words of its sentence. It stays the engineer's
    question: the requirement is reported unpaired, with this reason counted on the run.
A field with no words to compare is left alone (no opinion). Off unless PAIRING_SUBJECT_GATE_ENABLED.
Pure: no database, no model.
"""

from __future__ import annotations

import re

from . import claims, field_links, field_vocabulary
from .config import settings

SUBJECT_DIFFERS = "subject_differs"
SUBJECT_UNKNOWN = "subject_unknown"

_WORD = re.compile(r"[a-z]+")
#: Words that say which bound or how it is stated, not which quantity (the min/max and wording rules own those).
_BOUND_WORDS = frozenset(
    [
        "minimum",
        "maximum",
        "min",
        "max",
        "shall",
        "should",
        "must",
        "will",
        "not",
        "exceed",
        "exceeds",
        "exceeding",
        "less",
        "greater",
        "more",
        "than",
        "at",
        "least",
        "most",
        "be",
        "is",
        "are",
        "no",
        "nominal",
        "required",
        "allowable",
        "allowed",
    ]
)


def _is_unit(token: str) -> bool:
    """A token that is a unit spelling (the one unit table, `claims.is_unit`), bare or in brackets."""
    return claims.is_unit(token) or claims.is_unit(token.strip("()[],;:"))


def quantity_words(text: object, sheet: str | None = None) -> frozenset[str]:
    """The words of `text` that name the quantity (see the module docstring); empty when it names none."""
    # a unit printed beside the quantity ("(MPa)", "kPa(g)", "bar", "degC") is how it is measured, not which quantity it is
    raw = " ".join(t for t in str(text or "").split() if not _is_unit(t))
    folded = field_links.canonical(raw)
    # a token with a digit (a tag, a clause number) or a single letter (what is left of a tag) names no quantity
    words = {
        w
        for t in folded.split()
        if not re.search(r"\d", t)
        for w in _WORD.findall(t)
        if len(w) > 1
    }
    own = {w.rstrip("s") for w in str(sheet or "").lower().split()}
    return frozenset(
        w
        for w in words
        if w not in field_vocabulary._NEUTRAL
        and w not in _BOUND_WORDS
        and w.rstrip("s") not in own
    )


def conflict(requirement: dict, fact: dict, sheet: str | None = None) -> str | None:
    """The reason this pairing is refused (`SUBJECT_DIFFERS`, `SUBJECT_UNKNOWN`), or None to allow it."""
    if not settings.pairing_subject_gate_enabled:
        return None
    field = quantity_words(fact.get("field_name"), sheet)
    if not field:
        return None  # nothing to compare on the sheet's side: no opinion
    subject = quantity_words(
        requirement.get("subject") or requirement.get("field"), sheet
    )
    if not subject:
        return SUBJECT_UNKNOWN
    return None if subject == field else SUBJECT_DIFFERS
