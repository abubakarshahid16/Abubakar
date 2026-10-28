"""A placeholder value ("*", "TBA", "by vendor") is never "stated" (planner,
28 Oct, audit of the live M-03 run): "MIN FLOW THERMAL * m3/h" passed "the
minimum flow is stated". Invented values only."""

from __future__ import annotations

import pytest

from tests.test_746_relief_valve_checklist import fact, results

SET = "set pressure"


def _set_pressure_status(f):
    rows = [
        r
        for r in results([f]).values()
        if "set pressure is stated" in r["text"].lower()
    ]
    assert rows
    return rows[0]["status"]


@pytest.mark.parametrize("value", ["*", "TBA", "by vendor", "later"])
def test_a_placeholder_with_a_unit_is_missing_not_stated(value):
    assert _set_pressure_status(fact(SET, value, "barg")) == "MISSING_INFORMATION"


def test_a_real_value_is_still_stated():
    assert _set_pressure_status(fact(SET, "10", "barg")) == "COMPLIANT"
