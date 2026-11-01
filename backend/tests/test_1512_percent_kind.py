"""#1512: a fraction printed under a % label can pass a percent check. Invented sheets.

Live percent cards: PSV-27 and PSV-28 (overpressure at most 21 % / 10 % of the set
pressure, a value stated as a percentage) and PSV-29 (built-up back pressure stated
as a percentage, at most 10 %).
"""

from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from app.config import settings
from tests.test_746_relief_valve_checklist import fact, results


def base(case="Fire"):
    return [
        fact("set pressure", "10", "barg"),
        fact("relief case", case),
        fact("valve type", "Conventional"),
    ]


def over(value, unit, case="Fire"):
    # the sheet prints the percentage under a "%" label (the unit may be missing)
    return [*base(case), fact("over pressure", value, unit, label="Over pressure %")]


def back(value, unit):
    return [*base(), fact("built up back pressure", value, unit)]


def set_switch(monkeypatch, on):
    monkeypatch.setattr(settings, "percent_kind_check_enabled", on)


def test_today_a_fraction_under_a_percent_label_is_decided(monkeypatch):
    """Pinned with the switch off: 0.30 % is read as 0.30 % and passes (the bug)."""
    set_switch(monkeypatch, False)
    assert results(back("0.30", "%"))["PSV-29"]["status"] == "COMPLIANT"
    assert results(over("0.30", "%"))["PSV-27"]["status"] == "COMPLIANT"
    assert results(over("0.30", "%", "Thermal"))["PSV-28"]["status"] == "COMPLIANT"
    assert results(over("0.30", None))["PSV-27"]["status"] == "COMPLIANT"


@pytest.mark.parametrize(
    "sheet,card",
    [
        (back("0.30", "%"), "PSV-29"),
        (over("0.30", "%"), "PSV-27"),
        (over("0.30", "%", "Thermal"), "PSV-28"),
        (over("0.30", None), "PSV-27"),
        (over("0.30", None, "Thermal"), "PSV-28"),
        (back("1", "%"), "PSV-29"),
    ],
)
def test_switch_on_a_fraction_sized_percent_goes_to_the_engineer(
    monkeypatch, sheet, card
):
    set_switch(monkeypatch, True)
    r = results(sheet)[card]
    assert r["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "with a % label - a fraction or a percent? engineer to confirm" in str(r)


@pytest.mark.parametrize("on", [False, True])
def test_unambiguous_values_decide_the_same_either_way(monkeypatch, on):
    set_switch(monkeypatch, on)
    assert results(back("5", "%"))["PSV-29"]["status"] == "COMPLIANT"
    assert results(back("30", "%"))["PSV-29"]["status"] == "NON_COMPLIANT"
    assert results(over("30", "%"))["PSV-27"]["status"] == "NON_COMPLIANT"
    assert results(over("15", "%"))["PSV-27"]["status"] == "COMPLIANT"
    assert results(over("15", None, "Thermal"))["PSV-28"]["status"] == "NON_COMPLIANT"
    # a bare number, no % label anywhere, was never decided as a percentage
    for printed in ("30", "0.30"):
        assert (
            results(back(printed, None))["PSV-29"]["status"] == "NEEDS_ENGINEER_REVIEW"
        )


def test_a_pressure_value_is_not_a_percent_and_is_untouched(monkeypatch):
    set_switch(monkeypatch, True)
    sheet = [*base(), fact("over pressure", "0.5", "barg")]
    assert results(sheet)["PSV-27"]["status"] == "COMPLIANT"  # 5 % of 10 barg


def test_the_kind_doubt_helper():
    def f(v):
        return {"raw_value": v}

    assert dc._percent_kind_doubt(f("0.30")).startswith("the sheet prints 0.30")
    assert dc._percent_kind_doubt(f("1")) is not None
    assert dc._percent_kind_doubt(f("1.5")) is None
    assert dc._percent_kind_doubt(f("0")) is None
    assert dc._percent_kind_doubt(f("n/a")) is None


def test_the_area_calculation_does_not_use_a_fraction_sized_percent(monkeypatch):
    from tests.test_777_api520_calcs import LIQUID, RULES, _get

    sheet = [f for f in LIQUID if f["field_name"] != "over pressure"]
    sheet.append(fact("over pressure", "0.30", "%"))
    set_switch(monkeypatch, False)
    assert dc.api520_liquid_area(_get(sheet), RULES)["area_mm2"] > 0  # today
    set_switch(monkeypatch, True)
    with pytest.raises(dc._NotCalculated, match="a fraction or a percent"):
        dc.api520_liquid_area(_get(sheet), RULES)
