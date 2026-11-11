"""R12 (#776), planner 2026-10-11 point 5, from s1's review of the real
relief-valve checks: (a) when the fluid phase is not stated but the fluid
service names the OTHER phase, a gas-only (or liquid-only) item is an
engineer's question - never a Meets, never "does not apply" on a guess;
(b) a value outside its field's plausible range (a specific heat ratio of 18)
is never "stated" and never fed to a calculation. Invented sheets only.
"""
from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from tests.test_746_relief_valve_checklist import PSV, fact, results

GAS_ITEMS = ("PSV-19", "PSV-20", "PSV-21")      # molecular weight, Z, k: gas or vapour only
LIQUID_ITEMS = ("PSV-22", "PSV-23")              # density, viscosity: liquid only


def test_a_gas_item_on_a_liquid_service_with_no_phase_is_a_question_not_a_meets():
    sheet = [fact("fluid", "Cooling water", page=1), fact("molecular weight", "18"),
             fact("compressibility", "1.0"), fact("specific heat ratio", "1.3")]
    r = results(sheet)
    for item in GAS_ITEMS:
        assert r[item]["status"] == dc.NEEDS_ENGINEER_REVIEW, item
        assert "'Cooling water' (page 1) suggests liquid" in r[item]["detail"]
        assert "engineer to confirm the fluid phase" in r[item]["detail"]


def test_a_liquid_item_on_a_gas_service_with_no_phase_is_a_question():
    r = results([fact("fluid", "Natural gas"), fact("density", "800", "kg/m3")])
    assert r["PSV-22"]["status"] == dc.NEEDS_ENGINEER_REVIEW
    assert "suggests gas" in r["PSV-22"]["detail"]


def test_a_service_that_implies_the_items_own_phase_changes_nothing():
    """Natural gas implies gas: a gas item with k stated still meets, as before."""
    before = results([fact("specific heat ratio", "1.3")])["PSV-21"]
    after = results([fact("fluid", "Natural gas"), fact("specific heat ratio", "1.3")])["PSV-21"]
    assert before["status"] == after["status"] == dc.COMPLIANT


@pytest.mark.parametrize("service", ["Water vapour", "Hydrocarbon mixture", "Boiler feed"])
def test_a_service_naming_both_phases_or_neither_implies_nothing(service):
    """Whole words only ('boil' is not 'oil'); both phases named implies nothing."""
    r = results([fact("fluid", service), fact("specific heat ratio", "1.3")])
    assert r["PSV-21"]["status"] == dc.COMPLIANT


def test_a_stated_phase_still_decides_as_before():
    r = results([fact("fluid", "Cooling water"), fact("fluid phase", "Gas"),
                 fact("specific heat ratio", "1.3")])
    assert r["PSV-21"]["status"] == dc.COMPLIANT          # the sheet's own phase wins


def test_the_guess_never_says_does_not_apply():
    r = results([fact("fluid", "Crude oil")])
    assert all(r[i]["status"] != dc.NOT_APPLICABLE for i in GAS_ITEMS)


def test_a_specific_heat_ratio_outside_the_plausible_range_is_never_stated():
    r = results([fact("fluid phase", "Gas"), fact("specific heat ratio", "18")])
    for item in ("PSV-21", "PSV-32"):      # "k is stated", "k is above 1"
        assert r[item]["status"] == dc.NEEDS_ENGINEER_REVIEW, item
        assert "18 (page 2) is outside the plausible range for this field (at most 1.7)" in r[item]["detail"]


@pytest.mark.parametrize("k", ["1.0001", "1.4", "1.67", "1.7"])
def test_a_plausible_k_is_treated_as_before(k):
    assert results([fact("fluid phase", "Gas"), fact("specific heat ratio", k)])["PSV-21"]["status"] == dc.COMPLIANT


def test_k_below_one_is_still_psv32s_own_finding():
    r = results([fact("fluid phase", "Gas"), fact("specific heat ratio", "0.9")])
    assert r["PSV-32"]["status"] == dc.NON_COMPLIANT


def test_the_area_calculation_refuses_an_implausible_k():
    from tests.test_777_api520_calcs import GAS
    sheet = [f for f in GAS if f["field_name"] != "specific heat ratio"] + [
        fact("specific heat ratio", "18"), fact("orifice area", "2.853", "in2")]
    calc = results(sheet)["PSV-C01"]
    assert calc["status"] == dc.NOT_CALCULATED
    assert "outside the plausible range" in calc["detail"]


def test_the_ranges_and_implications_live_in_the_rules_file():
    rules = dc.load_rules()
    assert rules["roles"]["specific_heat_ratio"]["plausible"] == {"max": 1.7}
    implied = rules["roles"]["fluid_phase"]["implied_by"]
    assert implied["role"] == "fluid" and set(implied["phases"]) == {"liquid", "gas"}
