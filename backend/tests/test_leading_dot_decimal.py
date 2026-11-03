"""#1515: a number written without its leading zero (".30", ".5 mm", "-.5") is
the decimal it looks like. With LEADING_DOT_DECIMAL_ENABLED off today's wrong
readings are pinned; with it on they are right and nothing else moves."""

from __future__ import annotations

import pytest

from app import claims, comparison, numparse
from app.config import settings


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "leading_dot_decimal_enabled", True)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "leading_dot_decimal_enabled", False)


@pytest.mark.parametrize("text", [".30", ".5", "-.5", "+.5", "< .5", ".5.3"])
def test_off_a_leading_dot_value_reads_no_number(off, text):
    # #1640: a dot glued before the digits is no comparator, so no number is read. These read
    # 30, 5, 5, 5, 5 and 5.3 before: a wrong number, "-.5" without its sign.
    assert claims.parse_value(text) is None


def test_off_a_leading_dot_measurement_is_silently_dropped(off):
    assert claims.extract_measurements("wall thickness min .5 mm") == ()


@pytest.mark.parametrize(
    "text,expected",
    [
        (".30", 0.30),
        (".5", 0.5),
        ("-.5", -0.5),
        ("+.5", 0.5),
        ("\u2212.5", -0.5),
        ("\u2013.5", -0.5),
        ("< .5", 0.5),
        ("≥ .5", 0.5),
        (".05", 0.05),
        ("1,000.5", 1000.5),
        ("0.3", 0.3),
        ("5", 5.0),
    ],
)
def test_on_a_leading_dot_decimal_is_the_decimal(on, text, expected):
    assert claims.parse_value(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text,expected",
    [("set to 5.", None), ("5.", 5.0), ("p.4", None), ("approx. 5", 5.0)],
)
def test_on_a_sentence_final_or_glued_dot_is_not_a_decimal(on, text, expected):
    # #1640: words that are no comparator or qualifier ("set to") and a glued "p." give None;
    # "approx." is a qualifier and reads 5 as before (#1655).
    assert claims.parse_value(text) == expected


@pytest.mark.parametrize("text", [".", "-.", ".5.3", "0.3-.5", "...5", ". 5"])
def test_on_anything_ambiguous_is_no_value(on, text):
    assert claims.parse_value(text) is None


def test_on_a_range_with_a_leading_dot_end_is_reads_both_ends(on):
    assert [n.value for n in numparse.find_numbers("0.3-.5 bar")] == [0.3, 0.5]
    # the range reading is the one "0.3-0.5 bar" already gets: both ends, one unit
    assert [m.normalized_value for m in claims.extract_measurements("0.3-.5 bar")] == [
        pytest.approx(0.03),
        pytest.approx(0.05),
    ]


def test_on_a_leading_dot_measurement_is_read_with_its_unit(on):
    (m,) = claims.extract_measurements("wall thickness min .5 mm")
    assert (
        m.raw_value == ".5"
        and m.normalized_value == claims.normalise("0.5", "mm").normalized_value
    )
    (m,) = claims.extract_measurements("ambient -.5 C")
    assert m.normalized_value == claims.normalise("-0.5", "C").normalized_value < 0


def test_on_a_dot_inside_a_number_or_after_a_letter_is_no_new_measurement(on):
    assert [m.raw_value for m in claims.extract_measurements("gap 3.5 mm, p.4 mm")] == [
        "3.5"
    ]
    assert (
        claims.extract_measurements("1,000.5 kPa")
        == claims.extract_measurements("1,000.5 kPa")
        == ()
    )


def _status(operator: str, limit: str, observed: str) -> str:
    requirement = {
        "requirement_type": "numeric_limit",
        "operator": operator,
        "raw_value": limit,
        "raw_unit": "mm",
    }
    fact = {
        "id": "f1",
        "field_name": "wall thickness",
        "raw_value": observed,
        "raw_unit": "mm",
        "unit": "mm",
    }
    return comparison.compare(requirement, fact)["status"]


def test_off_a_misread_leading_dot_no_longer_passes_a_minimum(off):
    # ".5 mm" against a 3 mm minimum is a FAIL; read as 5 it passed. Since #1640 the dot before
    # the digits gives no number, so the engineer reads it.
    assert _status(">=", "3", ".5") == comparison.NEEDS_ENGINEER_REVIEW


def test_on_a_minimum_fails_a_leading_dot_value_below_it(on):
    assert _status(">=", "3", ".5") != comparison.COMPLIANT
    assert _status(">=", ".5", "3") == comparison.COMPLIANT
    assert _status(">=", ".5", ".3") != comparison.COMPLIANT


def test_on_a_maximum_passes_a_leading_dot_value_below_it(on):
    assert _status("<=", "3", ".5") == comparison.COMPLIANT
    assert _status("<=", ".5", "3") != comparison.COMPLIANT
    assert _status("<=", ".30", ".25") == comparison.COMPLIANT


def test_off_a_maximum_is_falsely_failed_by_a_misread_leading_dot(off):
    assert _status("<=", "3", ".5") != comparison.COMPLIANT


def test_the_switch_reaches_numparse_without_numparse_importing_the_app(on):
    # numparse must stay free of app imports (test_w2_number_parser); the
    # switch arrives through app.config instead (#1517 CI).
    from app import numparse

    assert numparse.LEADING_DOT_SWITCH is not None
    assert numparse.parse_value(".5") == 0.5
