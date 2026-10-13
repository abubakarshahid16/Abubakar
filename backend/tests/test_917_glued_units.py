"""#917 (PF3): a number glued to a one-letter unit ("230V", "5A", "40C", "3m")
is a quantity unless the context says it is a designator; every skip is
counted by reason.

Invented sentences only.
"""
from __future__ import annotations

import pytest

from app import claims


def _read(sentence: str):
    skips: dict[str, int] = {}
    found = claims.extract_measurements(sentence, skips)
    return [(m.raw_value, m.raw_unit) for m in found], skips


@pytest.mark.parametrize("sentence, value, unit", [
    ("Supply shall be 230V single phase.", "230", "V"),
    ("Rated current 5A at full load.", "5", "A"),
    ("Ambient up to 40C in the shade.", "40", "C"),
    ("Cable length 3m maximum.", "3", "m"),
    ("Rated 24V DC.", "24", "V"),
])
def test_a_glued_one_letter_unit_is_a_quantity(sentence, value, unit):
    got, skips = _read(sentence)
    assert any(v == value and u.lower() == unit.lower() for v, u in got), (sentence, got)
    assert skips == {}


@pytest.mark.parametrize("sentence", [
    "Coating system no. 5A shall be used.",
    "Use coating system 5A and 5B for the shell.",
    "Types 7A/7B are listed in the table.",
])
def test_a_designator_is_still_not_a_quantity_and_is_counted(sentence):
    got, skips = _read(sentence)
    assert not any(u.upper() in ("A", "B") for _v, u in got), got
    assert sum(skips.values()) >= 1 and set(skips) <= {claims.SKIP_DESIGNATOR_LEAD, claims.SKIP_DESIGNATOR_LIST}


def test_a_list_of_quantities_is_not_a_list_of_designators():
    got, skips = _read("Supply 230V or 24V, 50Hz.")
    assert ("230", "V") in got and ("24", "V") in got and skips == {}


def test_a_lone_lowercase_letter_with_a_space_is_a_word_and_is_counted():
    got, skips = _read("Apply 3 a coat of paint.")
    assert got == [] and skips == {claims.SKIP_LONE_LETTER_WORD: 1}


def test_a_sentence_opening_with_a_glued_letter_is_a_name_and_is_counted():
    got, skips = _read("5A to be tested shall be 6 mm.")
    assert ("6", "mm") in got and not any(x == "A" for _v, x in got)
    assert skips == {claims.SKIP_SENTENCE_INITIAL: 1}
