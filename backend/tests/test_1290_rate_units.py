"""#1290 (PF1 relief valve): a flow in another unit of the same quantity is compared.

Found by the PF1 invented group: "relieving capacity at least 1.0 kg/s" against
a sheet value of "3,700 kg/h" came back `unit_mismatch` ("not the same
quantity") because the unit table converted kg/h and m3/h but no other rate:
the per-time part was never converted. Every factor is a definition. Invented
values only.
"""

from __future__ import annotations

import pytest

from app import claims, comparison, rate_units
from tests import test_882_required_never_submitted as base

_review = base._review
world = base.world  # the same throw-away database fixture


def _limit(subject, operator, value, unit):
    return {
        "subject": subject,
        "operator": operator,
        "raw_value": value,
        "raw_unit": unit,
        "requirement_type": "numeric_limit",
    }


@pytest.mark.parametrize(
    "unit,value,base_value,dimension",
    [
        ("kg/s", "1", 3600.0, "mass_flow"),
        ("kg/min", "1", 60.0, "mass_flow"),
        ("kg/h", "5", 5.0, "mass_flow"),
        ("kg/hr", "5", 5.0, "mass_flow"),
        ("kg/d", "24", 1.0, "mass_flow"),
        ("g/s", "1", 3.6, "mass_flow"),
        ("t/h", "2", 2000.0, "mass_flow"),
        ("lb/h", "1000", 453.59237, "mass_flow"),
        ("lb/min", "1", 27.2155422, "mass_flow"),
        ("L/min", "60", 3.6, "volumetric_flow"),
        ("l/s", "1", 3.6, "volumetric_flow"),
        ("ml/min", "1000", 0.06, "volumetric_flow"),
        ("m3/s", "1", 3600.0, "volumetric_flow"),
        ("m3/h", "7", 7.0, "volumetric_flow"),
        ("m3/hr", "7", 7.0, "volumetric_flow"),
        ("m³/h", "7", 7.0, "volumetric_flow"),
        ("ft3/h", "100", 2.8316846592, "volumetric_flow"),
        ("usgal/min", "100", 22.712470704, "volumetric_flow"),
    ],
)
def test_the_flow_rates_convert_to_the_two_flow_bases_in_the_one_table(
    unit, value, base_value, dimension
):
    m = claims.normalise(value, unit)
    assert m.dimension == dimension
    assert m.normalized_unit == ("kg/h" if dimension == "mass_flow" else "m3/h")
    assert m.normalized_value == pytest.approx(base_value, rel=1e-9)


@pytest.mark.parametrize(
    "unit",
    [
        "Nm3/h",  # a volume at a reference condition is not a volume
        "Sm3/d",
        "scf/min",
        "ton/h",  # short or long: not for code to say
        "gal/min",  # US or imperial
        "bbl/d",  # oil or beer
        "kg/month",  # not a fixed number of hours
        "kg/year",
        "mol/s",
    ],
)
def test_a_rate_whose_unit_is_not_exact_stays_unconverted(unit):
    assert unit.lower() not in rate_units.TABLE
    assert claims.normalise("5", unit).normalized_value is None


def test_the_time_part_is_only_ever_a_fixed_number_of_hours():
    assert set(rate_units._PER_HOUR) == {
        "h",
        "hr",
        "hrs",
        "hour",
        "min",
        "s",
        "sec",
        "d",
        "day",
    }


def test_a_mass_flow_and_a_volume_flow_are_not_the_same_quantity():
    assert (
        claims.normalise("1", "kg/s").dimension
        != claims.normalise("1", "m3/s").dimension
    )


@pytest.mark.parametrize(
    "text,rule,fact,status",
    [
        # the exact limit in another unit is met: 1.0 kg/s is 3600 kg/h
        (
            "The relieving capacity shall be at least 1.0 kg/s.",
            ("the relieving capacity", ">=", "1.0", "kg/s"),
            ("Relieving capacity", "3600 kg/h"),
            comparison.COMPLIANT,
        ),
        (
            "The relieving capacity shall be at least 1.0 kg/s.",
            ("the relieving capacity", ">=", "1.0", "kg/s"),
            ("Relieving capacity", "3,700 kg/h"),
            comparison.COMPLIANT,
        ),
        (
            "The flow shall not exceed 3.6 m3/h.",
            ("the flow", "<=", "3.6", "m3/h"),
            ("Flow", "60 L/min"),
            comparison.COMPLIANT,
        ),
        # clearly outside, in both directions: never a pass
        (
            "The relieving capacity shall be at least 1.0 kg/s.",
            ("the relieving capacity", ">=", "1.0", "kg/s"),
            ("Relieving capacity", "3,500 kg/h"),
            comparison.NON_COMPLIANT,
        ),
        (
            "The flow shall not exceed 3.6 m3/h.",
            ("the flow", "<=", "3.6", "m3/h"),
            ("Flow", "70 L/min"),
            comparison.NON_COMPLIANT,
        ),
        (
            "The feed shall not exceed 2 t/h.",
            ("the feed", "<=", "2", "t/h"),
            ("Feed", "0.8 kg/s"),
            comparison.NON_COMPLIANT,
        ),
    ],
)
def test_a_flow_in_another_unit_is_compared_not_sent_back_as_a_mismatch(
    world, text, rule, fact, status
):
    found, _ = _review(text, _limit(*rule), [(fact[0], fact[1], None, None)])
    assert found["compliance_status"] == status, found.get("ai_rationale")
    assert "unit_mismatch" not in (found.get("ai_rationale") or "")


@pytest.mark.parametrize(
    "limit_unit,value",
    [("kg/s", "3600 m3/h"), ("m3/h", "1 kg/s"), ("kg/s", "3600 Nm3/h")],
)
def test_a_flow_of_another_quantity_or_condition_is_never_a_pass(
    world, limit_unit, value
):
    found, _ = _review(
        "The capacity shall be at least 1.0 unit.",
        _limit("the capacity", ">=", "1.0", limit_unit),
        [("Capacity", value, None, None)],
    )
    assert found["compliance_status"] != comparison.COMPLIANT
