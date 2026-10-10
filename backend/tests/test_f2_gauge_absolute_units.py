"""#725 F2: one unit routine reads gauge and absolute pressures.

On the real PSV datasheet the set pressure is "340 psig". `claims.normalise`
returned no number for barg, psig, bara, psia, kPag or kg/cm2g, and
`comparison._measurement_from_fact` re-read the raw unit and ignored the value
the extraction had already normalised - so no pressure on that sheet could be
compared. Now the reference (gauge / absolute) is split off and KEPT, the base
unit converts, and a gauge value is never compared with an absolute one (they
differ by an atmosphere nobody recorded). Invented values only.
"""
from __future__ import annotations

import pytest

from app import claims, comparison

MPA_PER_PSI = 0.006894757


@pytest.mark.parametrize("value,unit,mpa,reference", [
    ("340", "psig", 340 * MPA_PER_PSI, "gauge"),
    ("10", "barg", 1.0, "gauge"),
    ("10", "bara", 1.0, "absolute"),
    ("14.7", "psia", 14.7 * MPA_PER_PSI, "absolute"),
    ("100", "kPag", 0.1, "gauge"),
    ("5", "kg/cm2g", 5 * 0.0980665, "gauge"),
    ("3.5", "bar (ga)", 0.35, "gauge"),
])
def test_a_gauge_or_absolute_pressure_has_a_number_and_keeps_its_reference(value, unit, mpa, reference):
    m = claims.normalise(value, unit)
    assert m.normalized_unit == "MPa"
    assert m.normalized_value == pytest.approx(mpa, rel=1e-4)
    assert m.reference == reference
    assert m.raw_unit == unit                      # the document's own spelling is kept
    assert m.dimension == "pressure"


def test_a_plain_unit_has_no_reference():
    assert claims.normalise("10", "bar").reference is None
    assert claims.normalise("95", "dB(A)").reference is None


def test_gauge_and_absolute_are_never_compared():
    gauge, absolute = claims.normalise("10", "barg"), claims.normalise("10", "bara")
    assert claims._compatible(gauge, absolute) is None


def test_gauge_converts_across_units_and_meets_a_plain_limit():
    # 145 psig is 10.0 barg: inside a "<= 10.5 barg" limit, outside "<= 9 barg"
    observed = claims.normalise("145", "psig")
    assert claims._compatible(observed, claims.normalise("10.5", "barg", "<=")) is True
    assert claims._compatible(observed, claims.normalise("9", "barg", "<=")) is False
    # a plain-unit limit meets a gauge value, as the comparison already treats it
    assert claims._compatible(observed, claims.normalise("12", "bar", "<=")) is True


def _requirement(**fields):
    base = {"id": "r", "standard_document_id": None, "requirement_type": "numeric_limit",
            "requirement_text": "The set pressure shall not exceed 25 barg.",
            "operator": "<=", "raw_value": "25", "raw_unit": "barg", "field": "set pressure",
            "exceptions": []}
    return {**base, **fields}


def _fact(**fields):
    base = {"id": "f", "document_id": None, "field_name": "set pressure",
            "field_label": "Set pressure", "field_value": "340 psig", "raw_value": "340",
            "raw_unit": "psig", "is_blank": 0, "blank_marker": None}
    return {**base, **fields}


def test_a_psig_value_is_compared_with_a_barg_limit():
    # 340 psig = 23.4 barg: within 25 barg, outside 20 barg
    assert comparison.compare(_requirement(), _fact())["status"] == comparison.COMPLIANT
    over = comparison.compare(_requirement(raw_value="20"), _fact())
    assert over["status"] == comparison.NON_COMPLIANT


def test_a_gauge_value_against_an_absolute_limit_goes_to_an_engineer_with_the_reason():
    verdict = comparison.compare(_requirement(raw_unit="bara"), _fact())
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert "gauge" in verdict["rationale"] and "absolute" in verdict["rationale"]


def test_the_stored_normalised_value_of_a_fact_is_used():
    """The extraction already normalised the value; the comparison must not
    throw it away by re-reading a spelling it cannot read."""
    fact = _fact(raw_unit="psig (By Contractor)", normalized_value=340 * MPA_PER_PSI, normalized_unit="MPa",
                 unit_reference="gauge")
    m = comparison._measurement_from_fact(fact)
    assert m.normalized_value == pytest.approx(340 * MPA_PER_PSI)
    assert m.normalized_unit == "MPa" and m.reference == "gauge"
    assert comparison.compare(_requirement(raw_value="20"), fact)["status"] == comparison.NON_COMPLIANT
