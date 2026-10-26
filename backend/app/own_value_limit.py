"""A reference that states its own value is a plain limit (order 214).

"The set pressure shall not exceed the vessel MAWP of 12 barg" names a
reference (the MAWP) but also gives its number. Read as a comparison with
another field of the sheet, the 12 barg was dropped and the clause went to an
engineer ("MAWP is not stated on the datasheet"). It is a limit of 12 barg on
the set pressure. General: any "<comparator> <noun phrase> of <number> <unit>".

Left alone on purpose: a phrase that picks one of several values ("the lesser
of 10 mm or 6 mm"), a number followed by "or / and / to" another number, a
unit the system cannot convert, and a reference with no number.
"""

from __future__ import annotations

import re

from . import requirements_3b as r3b

_OWN_VALUE = re.compile(
    r"(?P<cmp>"
    + r3b._CMP_RE
    + r")\s*(?:the\s+)?(?P<ref>[A-Za-z][A-Za-z0-9 \-/]{1,60}?)"
    r"\s+of\s+(?P<value>[-+]?" + r3b._VALUE + r")\s*(?P<unit>" + r3b._UNIT + r")"
    r"(?![\w/])(?!\s*(?:or|and|to)\s+\d)",
    re.IGNORECASE,
)
_PICKS_ONE = re.compile(
    r"\b(?:greater|lesser|higher|lower|larger|smaller|sum|total|difference|"
    r"average|ratio|half|twice|double|times|multiple|percent)\b",
    re.IGNORECASE,
)


def parse(sentence: str) -> dict | None:
    """The limit the sentence states through a reference, or None."""
    match = _OWN_VALUE.search(sentence or "")
    if match is None or _PICKS_ONE.search(match.group("ref")):
        return None
    operator = r3b._OPERATOR.get(r3b._canonical_comparator(match.group("cmp")))
    raw_unit = r3b.unit_token(match.group("unit"))
    measurement = (
        r3b.measure(match.group("value"), raw_unit) if operator and raw_unit else None
    )
    if measurement is None or measurement.normalized_unit is None:
        return None
    return {
        "operator": operator,
        "raw_value": match.group("value"),
        "raw_unit": raw_unit,
        "value": measurement.normalized_value,
        "unit": measurement.normalized_unit,
    }
