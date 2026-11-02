"""A heat exchanger checklist box reads the value the sheet gives (finding on an exchanger proof run).

Two general causes, both behind `datasheet_label_join_enabled` (off by default):
1. a split abbreviation: the stored name "tube o d" (printed "O.D.") matched no role, so "Tube outside
   diameter was not found" while the value was read;
2. the same number printed twice, once without its unit, was "two different values".
Invented labels and values only (rule 13). Nothing here lets a box say more than "stated".
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app.config import settings
from app.label_match import drop_unit_less_twins, joined_letters
from tests.test_746_relief_valve_checklist import fact

HEX = "Heat Exchanger"


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "datasheet_label_join_enabled", True)


def _row(facts, rule_id):
    rows = dc.evaluate(facts, equipment_type=HEX, page_texts={1: "x"})
    return next(r for r in rows if r.get("checklist") and r["rule_id"] == rule_id)


def test_joined_letters_joins_only_runs_of_single_letters():
    assert joined_letters("tube o d") == "tube od"
    assert joined_letters("a b c outlet") == "abc outlet"
    assert joined_letters("tube od") == "tube od"
    assert joined_letters("b maximum design pressure") == "b maximum design pressure"
    assert joined_letters("") == ""


def test_off_a_split_abbreviation_is_not_found():
    row = _row([fact("tube o d", "1.", "in", page=4)], "HEX-11")
    assert row["status"] == "MISSING_INFORMATION"


def test_on_a_split_abbreviation_is_the_tube_outside_diameter(on):
    row = _row([fact("tube o d", "1.", "in", page=4)], "HEX-11")
    assert row["status"] == "COMPLIANT"
    assert "(page 4)" in row["detail"]


@pytest.mark.parametrize(
    "name", ["tube i d", "shell o d", "o d", "tube p d", "x tube o d", "tube o d n"]
)
def test_on_an_unrelated_label_never_matches(on, name):
    row = _row([fact(name, "1.", "in", page=4)], "HEX-11")
    assert row["status"] == "MISSING_INFORMATION"


def test_on_a_blank_under_the_joined_label_is_missing_not_stated(on):
    row = _row([fact("tube o d", "n/a", blank="n/a", page=4)], "HEX-11")
    assert row["status"] == "MISSING_INFORMATION"


def test_off_a_unit_left_off_one_copy_is_two_values():
    row = _row(
        [
            fact("corrosion allowance", "0.0472", page=1),
            fact("corrosion allowance", "0.0472", "in", page=5),
        ],
        "HEX-08",
    )
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in row["detail"]


def test_on_a_unit_left_off_one_copy_is_one_value(on):
    row = _row(
        [
            fact("corrosion allowance", "0.0472", page=1),
            fact("corrosion allowance", "0.0472", "in", page=5),
        ],
        "HEX-08",
    )
    assert row["status"] == "COMPLIANT"
    assert "in" in row["detail"]


@pytest.mark.parametrize(
    "second",
    [("0.125", "in"), ("0.0472", "mm"), ("0.125", None)],
)
def test_on_different_numbers_or_units_stay_two_values(on, second):
    value, unit = second
    first = fact("corrosion allowance", "0.0472", "in", page=1)
    row = _row([first, fact("corrosion allowance", value, unit, page=5)], "HEX-08")
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in row["detail"]


def test_two_united_readings_that_disagree_on_the_unit_stay_apart(on):
    a, b = fact("x", "4", "in"), fact("x", "4", "mm")
    c = fact("x", "4")
    assert drop_unit_less_twins([a, b, c]) == [a, b, c]


def test_a_unit_less_reading_alone_is_kept():
    only = [fact("x", "4")]
    assert drop_unit_less_twins(only) == only
    assert drop_unit_less_twins([]) == []


@pytest.mark.parametrize("text", ["max 650", "not 650", "min 650"])
def test_on_a_bound_or_negation_without_a_unit_stays_a_second_value(on, text):
    bare = fact("design temperature", "650", page=1)
    bare["field_value"] = text
    row = _row([bare, fact("design temperature", "650.", "F", page=5)], "HEX-04")
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in row["detail"]


def test_on_the_stated_design_temperature_reaches_the_engineer_as_stated_only(on):
    rows = dc.evaluate(
        [
            fact("design temperature", "650", page=1),
            fact("design temperature", "650.", "F", page=5),
        ],
        equipment_type=HEX,
        page_texts={1: "x"},
    )
    row = next(r for r in rows if r.get("rule_id") == "HEX-04")
    assert row["status"] == "COMPLIANT"
    assert "650. F (page 5) is stated." in row["detail"]
    assert "meets" not in row["detail"] and "not " not in row["detail"]
    assert row["draft"] is True  # a draft checklist: the engineer still signs it off
