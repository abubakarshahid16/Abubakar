"""A reference that states its own value is a plain limit (order 214).

"The set pressure shall not exceed the vessel MAWP of 12 barg" names a
reference (the MAWP) but also gives its number. Read as a comparison with
another field of the sheet, the 12 barg was dropped and the clause went to an
engineer ("MAWP is not stated on the datasheet"). It is a limit of 12 barg on
the set pressure. General: any "<comparator> <noun phrase> of <number> <unit>".

Left alone on purpose (the clause stays with an engineer, never a wrong Meets):
- a phrase that picks one of several values ("the lesser of 10 mm or 6 mm");
- a number just before the comparator ("10 % above", "2 bar below"): the limit
  is the stated value moved by that number, not the stated value;
- anything after the unit except the end of the sentence or a plain trailing
  clause ("minus 1 bar", "multiplied by 1.5", "by at least 10 %", "per 100 m",
  "at 40 C"): an allow-list, so a new wording cannot slip through;
- a unit the system cannot convert, and a reference with no number.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache

from . import numparse


@cache
def _patterns() -> tuple[re.Pattern, ...]:
    """Built on first use: this module is imported by `requirements_3b`, whose
    vocabulary the patterns are made of."""
    from . import requirements_3b as r3b

    own_value = re.compile(
        r"(?P<cmp>"
        + r3b._CMP_RE
        + r")\s*(?:the\s+)?(?P<ref>[A-Za-z][A-Za-z0-9 \-/]{1,60}?)"
        r"\s+of\s+(?P<value>[-+]?" + r3b._VALUE + r")\s*(?P<unit>" + r3b._UNIT + r")"
        r"(?![\w/])(?!\s*(?:or|and|to)\s+\d)",
        re.IGNORECASE,
    )
    picks_one = re.compile(
        r"\b(?:greater|lesser|higher|lower|larger|smaller|sum|total|difference|"
        r"average|ratio|half|twice|double|times|multiple|percent)\b",
        re.IGNORECASE,
    )
    number_before = re.compile(r"\d\s*(?:%|[A-Za-z]{1,6})?\s*$")
    # a trailing clause may follow a comma, but it holds no digit and no word
    # that moves, scales or chooses the number
    moves_number = re.compile(
        r"\d|%|\b(?:minus|plus|less|more|multiplied|divided|times|per|by|above|below|"
        r"over|under|whichever|greater|lesser|exceed|than)\b",
        re.IGNORECASE,
    )
    return own_value, picks_one, number_before, moves_number


def _stands_alone(sentence: str, match: re.Match) -> bool:
    """True when nothing before the comparator or after the unit changes the
    stated number."""
    _, _, number_before, moves_number = _patterns()
    if number_before.search(sentence[: match.start("cmp")]):
        return False
    tail = sentence[match.end() :]
    if re.match(r"\s*(?:[.;]|$)", tail):
        return True
    clause = re.match(r"\s*,([^.;]*)", tail)
    return clause is not None and not moves_number.search(clause.group(1))


def parse(sentence: str) -> dict | None:
    """The limit the sentence states through a reference, or None."""
    from . import requirements_3b as r3b

    own_value, picks_one, _, _ = _patterns()
    match = own_value.search(sentence or "")
    if match is None or picks_one.search(match.group("ref")):
        return None
    if not _stands_alone(sentence, match):
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


@cache
def _trailing_pattern() -> re.Pattern:
    from . import requirements_3b as r3b

    return re.compile(
        r"(?P<value>[-+]?" + r3b._VALUE + r")\s*(?P<unit>" + r3b._UNIT + r")"
        r"\s+(?P<cmp>or\s+[A-Za-z]+)\b",
        re.IGNORECASE,
    )


def _trailing_candidates(sentence: str) -> Iterator[tuple[re.Match, str, str]]:
    """Every "<number> <unit> or <comparator>" in the sentence, with its direction and
    unit. The direction is the shared vocabulary's (`comparators`)."""
    from . import comparators
    from . import requirements_3b as r3b

    for match in _trailing_pattern().finditer(sentence or ""):
        direction = comparators.direction_of(match.group(0))
        raw_unit = r3b.unit_token(match.group("unit"))
        if direction is not None and raw_unit:
            yield match, direction, raw_unit


def trailing_refused(sentence: str) -> bool:
    """A trailing limit in the sentence starts where no value may ("A-5 mm or less", "3-5 C
    or lower"). The text cannot say what it is, so NO limit of this sentence can be trusted:
    not a later value, and not a general limit whose exception it is. It goes to an engineer
    (#1619)."""
    starts = [found[0].start() for found in _trailing_candidates(sentence)]
    return any(not numparse.value_may_start(sentence, start) for start in starts)


def trailing(sentence: str) -> dict | None:
    """A comparator that FOLLOWS the value: "3 m or less", "5 mm or more". `_LIMIT`
    reads only one in front of the number."""
    from . import requirements_3b as r3b

    found = next(_trailing_candidates(sentence), None)
    if found is None or trailing_refused(sentence):
        return None
    match, direction, raw_unit = found
    measurement = r3b.measure(match.group("value"), raw_unit)
    return {
        "operator": direction,
        "raw_value": match.group("value"),
        "raw_unit": raw_unit,
        "value": measurement.normalized_value,
        "unit": measurement.normalized_unit,
    }
