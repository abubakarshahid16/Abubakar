"""Order 141 B: two units of ONE quantity are converted, then compared.

The review wrote "the requirement is in °F and the submitted value is in °C;
these are not the same quantity and were not compared". That was false: °F,
°C and K are one quantity, as are psi, bar, kPa and MPa, and inch and mm.
Now `claims.compare_across_units` converts them and decides the value as
written, as one unit is; it holds the value for the engineer only when what the
units leave open would change the answer:

  * a temperature is read as a temperature AND as a temperature difference
    (a rise), because the unit alone does not say which it is;
  * a gauge pressure against an absolute one is read for EVERY atmospheric
    pressure from none to the standard 101.325 kPa (the site's is unknown);
  * a value that is the limit to the precision both are printed to may be the
    limit printed in another unit, so it is held when the limit itself would
    get another answer.

Different quantities (a length against a temperature) stay uncompared.
Invented values only.
"""

from __future__ import annotations

import pytest

from app import claims, comparison, conditions, datasheet_checks, datasheets


def _requirement(value: str, unit: str, operator: str = "<=") -> dict:
    return {
        "id": "r",
        "standard_document_id": None,
        "requirement_type": "numeric_limit",
        "requirement_text": "An invented limit.",
        "operator": operator,
        "raw_value": value,
        "raw_unit": unit,
        "field": "design temperature",
        "exceptions": [],
    }


def _fact(value: str, unit: str) -> dict:
    return {
        "id": "f",
        "document_id": None,
        "field_name": "design temperature",
        "field_label": "Design temperature",
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "is_blank": 0,
        "blank_marker": None,
    }


def _status(limit: tuple, value: tuple) -> str:
    return comparison.compare(_requirement(*limit), _fact(*value))["status"]


def _why(limit: tuple, value: tuple) -> str:
    return comparison.compare(_requirement(*limit), _fact(*value))["rationale"]


C, NC, ENG = (
    comparison.COMPLIANT,
    comparison.NON_COMPLIANT,
    comparison.NEEDS_ENGINEER_REVIEW,
)


# ------------------------------------------------------------ temperatures


def test_a_fahrenheit_limit_and_a_celsius_value_are_compared():
    # 300 °F is 148.9 °C
    assert _status(("300", "°F"), ("140", "°C")) == C
    assert _status(("300", "°F", ">="), ("100", "°C")) == NC
    assert _status(("650", "°F"), ("380", "°C")) == NC


def test_a_celsius_limit_and_a_fahrenheit_value_are_compared():
    # 150 °C is 302 °F
    assert _status(("150", "°C"), ("310", "°F")) == NC
    assert _status(("150", "°C", ">="), ("320", "°F")) == C
    assert _status(("60", "deg C"), ("100", "degF")) == C


def test_the_finding_says_how_the_limit_was_converted():
    why = _why(("300", "°F"), ("140", "°C"))
    assert "300 °F is 148.89 °C" in why
    assert "temperature differences" in why


def test_a_converted_value_at_the_limit_goes_to_an_engineer_not_a_verdict():
    """304 °F is 151.11 °C. "151 °C" is that limit to the precision both are
    printed to (0.5 °F, 0.5 °C), so it may be the limit written in °C: as
    written it misses a minimum the limit itself meets. Held."""
    verdict = comparison.compare(_requirement("304", "°F", ">="), _fact("151", "°C"))
    assert verdict["status"] == ENG
    assert "precision both are printed to" in verdict["rationale"]
    assert _status(("304", "°F", ">="), ("180", "°C")) == C  # control: clear of it
    # the other direction: 151 °C is 303.8 °F
    assert _status(("151", "°C"), ("304", "°F")) == ENG
    # an exact-value limit: 70 °F is 21.11 °C
    assert _status(("70", "°F", "="), ("21", "°C")) == ENG
    assert _status(("300", "°F", "="), ("149", "°C")) == ENG


def test_a_value_clear_of_the_limit_by_more_than_the_printing_is_decided_as_written():
    """650 °F is 343.33 °C; "343 °C" is 0.33 °C off it, more than the limit's
    own printing (0.5 °F = 0.28 °C), so it is decided as written, as one unit
    would be."""
    assert _status(("650", "°F"), ("343", "°C")) == C
    assert _status(("650", "°F", ">="), ("343", "°C")) == NC  # misses a minimum
    assert _status(("650", "°F"), ("340", "°C")) == C


def test_a_value_exactly_at_the_limit_after_an_exact_conversion_is_compared_as_written():
    # 212 °F is exactly 100 °C; 2 in is exactly 50.8 mm
    assert _status(("212", "°F"), ("100", "°C")) == C
    assert _status(("2", "in"), ("50.8", "mm")) == C


def test_a_rise_in_kelvin_and_a_rise_in_celsius_are_never_confused_with_temperatures():
    """80 K as a RISE is 80 °C of rise; as a temperature it is -193 °C. 65 °C
    is within the rise and far above the temperature: the readings disagree,
    so it is an engineer's check - never a false breach."""
    verdict = comparison.compare(_requirement("80", "K"), _fact("65", "°C"))
    assert verdict["status"] == ENG
    assert "temperature difference" in verdict["rationale"]
    # 90 °C is outside 80 K read either way: a real breach is still caught
    assert _status(("80", "K"), ("90", "°C")) == NC
    # 50 °C is within 400 K read either way
    assert _status(("400", "K"), ("50", "°C")) == C


def test_fahrenheit_and_celsius_readings_that_disagree_go_to_an_engineer():
    """300 °F: 148.9 °C as a temperature, 166.7 °C as a difference. 160 °C is
    outside the first and inside the second."""
    verdict = comparison.compare(_requirement("300", "°F"), _fact("160", "°C"))
    assert verdict["status"] == ENG
    assert "the answer depends on it" in verdict["rationale"]


# --------------------------------------------------------------- pressures


def test_psi_bar_and_kpa_are_compared():
    assert _status(("10", "bar"), ("140", "psi")) == C  # 9.65 bar
    assert _status(("10", "bar"), ("150", "psi")) == NC  # 10.34 bar
    assert _status(("1000", "kPa"), ("10.5", "bar")) == NC
    assert _status(("1", "MPa"), ("950", "kPa")) == C
    assert _status(("10", "bar"), ("1000", "kPa")) == C  # exactly the limit


def test_a_pressure_converted_near_its_limit_is_held_only_when_the_limit_would_differ():
    # 145 psi is 9.997 bar: 10 bar printed in psi. Within a maximum either way.
    assert _status(("10", "bar"), ("145", "psi")) == C
    # ...but it misses a minimum and an exact value the limit itself meets
    assert _status(("10", "bar", ">="), ("145", "psi")) == ENG
    assert _status(("10", "bar", "="), ("145", "psi")) == ENG


def test_whole_numbers_keep_the_verdict_one_unit_would_give():
    """A whole number is not a band of +-half a unit: 10 barg (145 psig) is
    within 150 psig, 4 in (101.6 mm) meets 100 mm, 6 mm misses 0.25 in."""
    assert _status(("150", "psig"), ("10", "barg")) == C
    assert _status(("100", "mm", ">="), ("4", "in")) == C
    assert _status(("0.25", "in", ">="), ("6", "mm")) == NC
    assert _status(("50", "psia"), ("2", "barg")) == C


def test_barg_and_psig_are_compared():
    assert _status(("10", "barg"), ("140", "psig")) == C
    assert _status(("10", "barg"), ("150", "psig")) == NC


def test_an_absolute_limit_and_a_gauge_value_are_compared_when_the_atmosphere_cannot_decide():
    verdict = comparison.compare(_requirement("10", "bara"), _fact("5", "barg"))
    assert verdict["status"] == C
    assert "every atmospheric pressure" in verdict["rationale"]
    assert "standard 101.325 kPa" in verdict["rationale"]
    assert _status(("4", "bara"), ("5", "barg")) == NC
    assert _status(("10", "barg", ">="), ("5", "bara")) == NC


def test_an_absolute_limit_and_a_gauge_value_the_atmosphere_decides_go_to_an_engineer():
    # 3.5 barg is 4.51 bara at sea level and less at altitude: against 4 bara
    # the site's atmospheric pressure decides
    verdict = comparison.compare(_requirement("4", "bara"), _fact("3.5", "barg"))
    assert verdict["status"] == ENG
    assert "atmospheric pressure is not recorded" in verdict["rationale"]
    # an exact value BETWEEN the two ends: 10 barg is 10.5 bara at 0.5 bar
    # of atmosphere, so the whole range is tested, not only its ends
    assert _status(("10.5", "bara", "="), ("10.0", "barg")) == ENG


def test_an_absolute_value_against_a_limit_with_no_reference_is_still_not_compared():
    """Only a STATED reference on both sides is converted (R32 stays)."""
    for limit in (("10", "bar"), ("1000", "kPa")):  # one unit, and two
        verdict = comparison.compare(_requirement(*limit), _fact("5", "bara"))
        assert verdict["status"] == ENG
        assert "no reference" in verdict["rationale"]


# ----------------------------------------------------------------- lengths


def test_inches_and_millimetres_are_compared():
    assert _status(("2", "in"), ("50", "mm")) == C
    assert _status(("2", "in"), ("52", "mm")) == NC
    assert _status(("2", "in"), ("51", "mm")) == ENG  # 50.8 mm, within the printing


# --------------------------------------------------- different quantities


def test_different_quantities_stay_uncompared():
    verdict = comparison.compare(_requirement("10", "mm"), _fact("5", "°C"))
    assert verdict["status"] == ENG
    assert "no conversion is guessed" in verdict["rationale"]
    assert (
        claims.compare_across_units(
            claims.normalise("5", "°C"), claims.normalise("10", "mm")
        )
        is None
    )


def _guard(requirement_unit: str, fact_unit: str) -> bool:
    """The unit guard as `run_comparison` and the candidate filter call it."""
    requirement = {"raw_value": "300", "raw_unit": requirement_unit, "operator": "<="}
    fact = {"raw_value": "140", "raw_unit": fact_unit, "is_blank": 0}
    return comparison._units_comparable(
        requirement,
        fact,
        comparison._unit_measure(requirement),
        comparison._unit_measure(fact),
    )


@pytest.mark.parametrize(
    "left,right", [("°F", "°C"), ("°C", "°F"), ("K", "°C"), ("degF", "K")]
)
def test_the_run_unit_guard_lets_two_temperature_scales_through(left, right):
    assert _guard(left, right) is True


@pytest.mark.parametrize(
    "left,right", [("mm", "°C"), ("°F", "psi"), ("dB(A)", "dB"), ("years", "hours")]
)
def test_the_run_unit_guard_still_refuses_different_quantities(left, right):
    assert _guard(left, right) is False


# --------------------------------------------------------------- one home


def test_the_api520_calculations_read_the_same_temperature_table_and_atmosphere():
    assert datasheet_checks._TEMPERATURE is claims.TEMPERATURE_SCALES
    assert datasheet_checks.ATMOSPHERIC_KPA == claims.STANDARD_ATMOSPHERE_KPA == 101.325


def test_the_dual_unit_cell_check_reads_the_same_temperature_table():
    assert datasheets._celsius(212.0, "°F") == pytest.approx(100.0)
    assert datasheets._celsius(373.15, "K") == pytest.approx(100.0)
    assert datasheets._celsius(100.0, "ºC") == pytest.approx(100.0)
    assert datasheets._celsius(100.0, "°R") is None
    assert datasheets.same_quantity_twice("150", "°C", "302", "°F")


# ------------------------------------------------- the v1 condition gate


def _threshold(condition: str, value: str, unit: str, name: str) -> str:
    fact = {
        "id": "f",
        "field_name": name,
        "field_value": f"{value} {unit}",
        "raw_value": value,
        "raw_unit": unit,
        "document_id": None,
        "page_no": 1,
    }
    return conditions._evaluate_numeric(condition, [fact])["state"]


def test_the_v1_condition_gate_reads_its_operator_the_right_way_round():
    """ "Greater than 25 mm" is satisfied by 30 mm. The operator sat on the
    fact, so 30 mm read as NOT satisfied and the clause was excused."""
    assert (
        _threshold("thickness greater than 25 mm", "30", "mm", "thickness")
        == conditions.SATISFIED
    )
    assert (
        _threshold("thickness greater than 25 mm", "20", "mm", "thickness")
        == conditions.NOT_SATISFIED
    )
    assert (
        _threshold("thickness less than 25 mm", "20", "mm", "thickness")
        == conditions.SATISFIED
    )


def test_the_v1_condition_gate_converts_a_fahrenheit_threshold():
    """The same refusal order 141 B removes: "650 °F" against a °C value was
    "cannot be compared"."""
    cond = "design temperature greater than 650 °F"
    assert _threshold(cond, "400", "°C", "design temperature") == conditions.SATISFIED
    assert (
        _threshold(cond, "300", "°C", "design temperature") == conditions.NOT_SATISFIED
    )
    assert (
        _threshold("thickness greater than 1 in", "30", "mm", "thickness")
        == conditions.SATISFIED
    )
