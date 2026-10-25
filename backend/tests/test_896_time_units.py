"""#896 (PF2): a value in another unit of the same quantity is compared.

Found by the PF1 invented group: "at least 8 minutes" against "480 s" and "shall
not exceed 250 ms" against "0.2 s" came back `unit_mismatch` ("not the same
quantity") because the time table held hours and minutes but not seconds,
milliseconds or days. Temperature (°C/°F) and gauge pressure (barg/psig)
already converted on main. Invented values only.
"""

from __future__ import annotations

import pytest

from app import claims, comparison
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
    "unit,value,hours",
    [
        ("s", "3600", 1.0),
        ("sec", "60", 1 / 60),
        ("seconds", "90", 0.025),
        ("ms", "1000", 1 / 3600),
        ("milliseconds", "250", 250 / 3600000),
        ("day", "1", 24.0),
        ("days", "2", 48.0),
        ("Seconds", "30", 30 / 3600),
        ("minutes", "8", 8 / 60),
    ],
)
def test_the_time_units_convert_to_hours_in_the_one_table(unit, value, hours):
    m = claims.normalise(value, unit)
    assert m.normalized_unit == "h" and m.dimension == "time"
    assert m.normalized_value == pytest.approx(hours, rel=1e-12)


@pytest.mark.parametrize(
    "text,rule,fact,status",
    [
        # the exact limit in another unit is met (8 min = 480 s; 250 ms = 0.25 s)
        (
            "The test time shall be at least 8 minutes.",
            ("the test time", ">=", "8", "minutes"),
            ("Test time", "480 s"),
            comparison.COMPLIANT,
        ),
        (
            "The response time shall not exceed 250 ms.",
            ("the response time", "<=", "250", "ms"),
            ("Response time", "0.25 s"),
            comparison.COMPLIANT,
        ),
        # clearly inside
        (
            "The response time shall not exceed 250 ms.",
            ("the response time", "<=", "250", "ms"),
            ("Response time", "0.2 s"),
            comparison.COMPLIANT,
        ),
        (
            "The hold time shall be at least 1 hour.",
            ("the hold time", ">=", "1", "hour"),
            ("Hold time", "2 days"),
            comparison.COMPLIANT,
        ),
        # clearly outside, in both directions: never a pass
        (
            "The test time shall be at least 8 minutes.",
            ("the test time", ">=", "8", "minutes"),
            ("Test time", "400 s"),
            comparison.NON_COMPLIANT,
        ),
        (
            "The response time shall not exceed 250 ms.",
            ("the response time", "<=", "250", "ms"),
            ("Response time", "0.3 s"),
            comparison.NON_COMPLIANT,
        ),
        (
            "The stroke time shall be not more than 0.5 minutes.",
            ("the stroke time", "<=", "0.5", "minutes"),
            ("Stroke time", "45 s"),
            comparison.NON_COMPLIANT,
        ),
    ],
)
def test_a_time_in_another_unit_is_compared_not_sent_back_as_a_mismatch(
    world, text, rule, fact, status
):
    found, _ = _review(text, _limit(*rule), [(fact[0], fact[1], None, None)])
    assert found["compliance_status"] == status, found.get("ai_rationale")
    assert "unit_mismatch" not in (found.get("ai_rationale") or "")


def test_a_time_against_a_different_quantity_is_still_not_compared(world):
    """Dimension still does its job: seconds against a pressure limit."""
    found, _ = _review(
        "The pressure shall be not more than 4 bar.",
        _limit("the pressure", "<=", "4", "bar"),
        [("Pressure", "3 s", None, None)],
    )
    assert found["compliance_status"] != comparison.COMPLIANT


def test_a_bare_s_after_a_number_is_a_second_and_nothing_else_changes():
    """The new single-letter unit must not turn running text into measurements:
    extraction still ignores a letter that is not a unit of a number."""
    assert claims.normalise("5", "s").normalized_value == pytest.approx(5 / 3600)
    assert claims.normalise("5", "x").normalized_value is None
