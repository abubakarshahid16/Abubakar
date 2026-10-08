"""#193: a limit whose unit is thrown away can never be compared.

Measured on real standards (scratch copy, 2026-09-26): 24 of 93 matchable
limits were stored with no unit, 20 of them because the unit was printed and
not recognised - flow in L/s, application rates in L/m2s and L/(m2s), gauge
and absolute pressures written kPag and psia, and an area glued to its own
conversion, "1,800 m2(20,000 ft2)". Sentences below are synthetic.
"""
from __future__ import annotations

import pytest

from app import claims, requirements_3b


@pytest.mark.parametrize("sentence, unit", [
    ("The flow shall not exceed 378 L/s (6,000 gpm).", "L/s"),
    ("Residual pressure shall not exceed 1,140 kPag (165 psig).", "kPag"),
    ("The vapour pressure shall be lower than 13 psia (89632 Pa).", "psia"),
    ("The application density shall be at least 0.14 L/m2s ( 0.20 gpm/ft2).", "L/m2s"),
    ("The application rate shall be at least 0.07 L/(m2s).", "L/(m2s)"),
    ("The surface shall not exceed 1,800 m2(20,000 ft2).", "m2"),
    ("The unit weight shall be at least 14.1 kN/m3.", "kN/m3"),
    ("The illumination shall be at least 110 lux.", "lux"),
])
def test_a_printed_unit_is_kept(sentence, unit):
    assert requirements_3b.parse_limit(sentence)["raw_unit"] == unit


@pytest.mark.parametrize("sentence, unit", [
    ("Equipment noise shall not exceed 90 dB(A).", "dB(A)"),
    ("The solids loading shall not exceed 5 g/L.", "g/L"),
    ("The spacing shall be at least 7.5 m (25 ft).", "m"),
])
def test_units_that_already_worked_are_unchanged(sentence, unit):
    assert requirements_3b.parse_limit(sentence)["raw_unit"] == unit


@pytest.mark.parametrize("sentence", [
    "Samples shall be taken in at least 3 locations.",
    "The test shall be repeated at least 2 times.",
])
def test_a_word_that_is_not_a_unit_is_still_not_a_unit(sentence):
    assert requirements_3b.parse_limit(sentence)["raw_unit"] is None


def test_absolute_and_gauge_pressures_never_compare_as_one_unit():
    """Recognised, not converted: 13 psia is not 13 psig."""
    psia = claims.normalise("13", "psia")
    psig = claims.normalise("13", "psig")
    assert psia.normalized_value is None and psig.normalized_value is None
    assert not claims.same_unit(psia, psig)
    assert claims.unit_dimension("kPag") == claims.unit_dimension("psia") == "pressure"
