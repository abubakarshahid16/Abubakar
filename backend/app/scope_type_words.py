"""Words of a division's construction against the sheet's own type (order 210, FIX 2).

A standard's division limited to "centrifugal pumps" applies to a sheet whose
equipment type or title already says "Centrifugal Pump". The model was asked
whether the equipment is of that construction and answered "unsure" without
quoting the type line (21 of 35 replies on the invented set), which held the
whole standard. `construction_in_type` is the code-side check of the words: it
is a DRAFT, OFF until the owner says yes (`scope_type_words_rule_enabled`), and
it only lets a clause be checked; it never passes one. Nothing names a
standard, a type or a layout.
"""

from __future__ import annotations

import re

from . import subject_scope

#: Function words that carry no construction ("pumps FOR the oil service").
FUNCTION_WORDS = frozenset(
    {"a", "an", "the", "of", "for", "and", "or", "to", "in", "on", "with", "by"}
)
#: The note on a requirement of a standard's title block whose scope was not confirmed.
SCOPE_NOT_CONFIRMED = (
    "the standard's own scope sentence could not be tied to this equipment "
    "(the model was unsure or did not answer); the clause is compared as usual"
)


def words(text: object, least: int = 4) -> set[str]:
    """The words of `text` of `least` letters or more, a plural "s" dropped."""
    return {
        w[:-1] if w.endswith("s") else w
        for w in re.findall(rf"[a-z]{{{least},}}", subject_scope._fold(text))
    } - {""}


def construction_in_type(construction: str, classification: dict | None) -> bool:
    """Is EVERY word of the division's construction ("centrifugal pumps")
    already in the sheet's equipment type or title ("Centrifugal Pump")? Every
    word counts, a short one too (a plural "s" aside; only function words are
    left out), so "magnetic-drive pumps" does not match "Centrifugal Pump"."""
    classification = classification or {}
    named = f"{classification.get('equipment_type') or ''} {classification.get('title') or ''}"
    need = words(construction, least=1) - FUNCTION_WORDS
    return bool(need) and need <= words(named, least=1)
