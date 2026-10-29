"""Order 307 (found in the final CRS, row 76): a field the sheet gives TWICE in different forms is never said to be
"not given". Invented values only."""

from __future__ import annotations

from app import datasheet_checks as dc
from tests.test_746_relief_valve_checklist import PSV, fact

NAME = "viscosity at relieving temper"


def _reading(value, tag="PSV-A"):
    f = fact(NAME, value, None, tag=tag, page=4)
    f["raw_value"] = None
    return f


def _detail(facts):
    rows = dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
    return next(r for r in rows if r.get("checklist") and r["rule_id"] == "PSV-23")


def test_two_readings_of_one_field_are_not_called_not_given():
    row = _detail([_reading("4-28 cP By Contractor"), _reading("5-30 cP")])
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "has two different values on the sheet" in row["detail"]
    assert "is not given" not in row["detail"]


def test_a_field_that_is_absent_is_still_called_not_given():
    row = _detail([fact("set pressure", "10", "barg", tag="PSV-A", page=4)])
    assert row["status"] == "NEEDS_ENGINEER_REVIEW"
    assert (
        "is not given" in row["detail"] and "two different values" not in row["detail"]
    )
