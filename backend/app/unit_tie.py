"""A reader's unit sits with its number in the quote (#1653).

Every gate checked the value and the unit in a quote separately, so value 10 and unit MPa were
"proved" by "10 bar and 5 MPa". `unit_with_value` ties them by position only: which number a
printed unit follows. General, for any document (rule 13); the unit vocabulary is `claims`'.
"""

from __future__ import annotations

import re

from . import claims, numparse

#: What may stand between a number and its unit: space, a degree sign, an opening bracket ("10 (MPa)").
_UNIT_GAP = re.compile(r"[\s\u00b0(\[]*")
#: Between two numbers that print their unit once: a range ("10-12 MPa", "10 to 12 MPa"), a pair
#: ("23.5 / 9 barg") or a size ("10 x 12 mm").
_RANGE_GAP = re.compile(r"\s*(?:-|\u2013|\u2014|to|/|x|\u00d7)\s*")


def _owners(numbers: list, text: str, at: int) -> list:
    """The numbers a unit printed at `at` belongs to: the number right before it, and the first
    end of a range that prints the unit once."""
    before = [n for n in numbers if n.end <= at]
    if not before or not _UNIT_GAP.fullmatch(text[before[-1].end : at]):
        return []
    owners = [before[-1]]
    if len(before) > 1 and _RANGE_GAP.fullmatch(
        text[before[-2].end : before[-1].start]
    ):
        owners.append(before[-2])
    return owners


def unit_with_value(value: object, unit: str | None, text: object) -> bool:
    """Does `text` leave `unit` as the unit of the number `value`? (#1653)

    A reader's value and unit are each found in a quote by other checks; this one ties them.
    False when the quote prints the unit only after OTHER numbers ("10 bar and 5 MPa" for 10 MPa),
    or prints it apart from any number while the value carries a different unit of its own
    ("MPa: 10 bar"). True when the unit sits with the value ("10 MPa", "10 to 12 MPa", "10 (MPa)"),
    stands apart while the value has no unit beside it ("Pressure, MPa: 10"), or when the value is
    no bare number or the unit is not printed: other checks decide those. General: positions only."""
    wanted = numparse.as_number(value)
    folded_unit = numparse.fold(unit or "")
    if wanted is None or not folded_unit:
        return True
    folded = numparse.fold_numbers(text or "")
    numbers = [n for n in numparse.find_numbers(folded) if n.value is not None]
    printed = r"(?<![^\W\d_])" + re.escape(folded_unit) + r"(?![^\W_])"
    places = [m.start() for m in re.finditer(printed, folded)]
    if not places:
        return True  # not printed: the unit-in-quote check refuses it
    owners = [o for at in places for o in _owners(numbers, folded, at)]
    if owners:
        return any(o.value == wanted and not o.joined for o in owners)
    for n in numbers:
        if n.value != wanted:
            continue
        after = re.match(r"[\s\u00b0]*([^\s,;:()]+)", folded[n.end :])
        word = after.group(1).rstrip(".") if after else ""
        if (
            word
            and claims.is_unit(word)
            and claims._fold_unit(word) != claims._fold_unit(folded_unit)
        ):
            return False
    return True
