"""R13 (#777): engineering calculations by code - the PSV required area per
API 520-I, recomputed from the sheet's own inputs and compared with the
selected orifice area and with the required area the sheet states.

What must hold: the formulas reproduce API 520-I's own worked examples, in SI
and in US units alike; a mismatch is a finding with both numbers, the clause
and every input; an area that is only a lower bound (a simplification the
sheet does not rule out) is never a pass; a missing or unreadable input skips
the calculation with its reason and is never a comment; a percentage limit on
a value stated as a pressure is worked out from the set pressure. The AI does
no arithmetic. Invented sheets only.
"""
from __future__ import annotations

import math

import pytest

from app import datasheet_checks as dc
from tests.test_746_relief_valve_checklist import PSV, fact

RULES = dc.load_rules()

#: API 520-I's gas sizing example figures (SI): W 24 270 kg/h, P1 670 kPa(a),
#: T 348 K, Z 0.90, M 51, k 1.11 -> about 3 698 mm2. Set pressure + overpressure
#: here add up to that P1.
GAS = [fact("required capacity", "24270", "kg/h"), fact("set pressure", "568.675", "kPa(g)"),
       fact("over pressure", "0", "kPa"), fact("relieving temperature", "348", "K"),
       fact("molecular weight", "51"), fact("compressibility", "0.90"),
       fact("specific heat ratio", "1.11"), fact("valve type", "Conventional"),
       fact("superimposed back pressure", "0", "barg"), fact("built up back pressure", "0.5", "barg"),
       fact("fluid phase", "Gas")]
#: API 520-I's liquid example figures (SI): Q 6 814 L/min, G 0.90, set 1 724
#: kPa(g) + 10 %, back pressure 345 kPa(g) -> about 3 066 mm2 with Kw 0.97,
#: so 3 066 x 0.97 with Kw 1.0.
LIQUID = [fact("required capacity", "6814", "l/min"), fact("density", "899.1", "kg/m3"),
          fact("set pressure", "1724", "kPa(g)"), fact("over pressure", "10", "%"),
          fact("superimposed back pressure", "0", "kPa"), fact("built up back pressure", "345", "kPa(g)"),
          fact("valve type", "Conventional"), fact("viscosity", "1", "cP"), fact("fluid phase", "Liquid")]


def _get(facts):
    roles = {}
    for f in facts:
        roles.setdefault(dc.role_of(f["field_name"], RULES), []).append(f)
    return lambda role: roles.get(role, [])


def results(facts):
    return {r["rule_id"]: r for r in dc.evaluate(facts, equipment_type=PSV, page_texts={1: "x"})
            if r.get("checklist")}


def _without(facts, name):
    return [f for f in facts if f["field_name"] != name]


def test_the_gas_formula_reproduces_the_standards_worked_example():
    calc = dc.api520_gas_area(_get(GAS), RULES)
    assert calc["area_mm2"] == pytest.approx(3698, rel=0.001)
    assert calc["lower_bound"] == []          # conventional, critical flow, back pressure known


def test_the_gas_formula_agrees_with_the_us_customary_form():
    """An independent check of every constant and unit: the US form of the
    same equation (C = 520 sqrt(...), lb/h, psia, R, in2) on the same inputs."""
    w, p1, t, z, m, k = 24270 / 0.45359237, 670 / 6.894757293168361, 348 * 1.8, 0.90, 51, 1.11
    c = 520 * math.sqrt(k * (2 / (k + 1)) ** ((k + 1) / (k - 1)))
    us_in2 = w / (c * 0.975 * p1) * math.sqrt(t * z / m)
    assert dc.api520_gas_area(_get(GAS), RULES)["area_mm2"] == pytest.approx(us_in2 * 645.16, rel=0.002)


def test_us_units_on_the_sheet_give_the_same_area():
    us = [fact("required capacity", f"{24270 / 0.45359237:.1f}", "lb/h"),
          fact("set pressure", f"{568.675 / 6.894757293168361:.4f}", "psig"),
          fact("over pressure", "0", "%"), fact("relieving temperature", f"{348 * 1.8 - 459.67:.3f}", "°F"),
          *[f for f in GAS if f["field_name"] in ("molecular weight", "compressibility",
                                                  "specific heat ratio", "valve type")]]
    assert dc.api520_gas_area(_get(us), RULES)["area_mm2"] == pytest.approx(3698, rel=0.001)


def test_the_liquid_formula_reproduces_the_standards_worked_example():
    no_viscosity = _without(LIQUID, "viscosity")
    calc = dc.api520_liquid_area(_get(no_viscosity), RULES)
    assert calc["area_mm2"] / 0.97 == pytest.approx(3066, rel=0.002)
    assert calc["lower_bound"] == ["the viscosity is not given, so Kv was taken as 1.0"]


def test_a_viscous_liquid_needs_a_larger_area_and_cst_is_converted():
    thin = dc.api520_liquid_area(_get(LIQUID), RULES)["area_mm2"]
    thick = _without(LIQUID, "viscosity") + [fact("viscosity", "2000", "cP")]
    as_cst = _without(LIQUID, "viscosity") + [fact("viscosity", f"{2000 / 0.8991:.3f}", "cSt")]
    assert dc.api520_liquid_area(_get(thick), RULES)["area_mm2"] > thin * 1.05
    assert dc.api520_liquid_area(_get(as_cst), RULES)["area_mm2"] == pytest.approx(
        dc.api520_liquid_area(_get(thick), RULES)["area_mm2"], rel=0.001)


def test_an_orifice_below_the_calculated_area_is_a_finding_with_both_numbers():
    r = results(GAS + [fact("orifice area", "2.853", "in2", label="Effective orifice area")])
    calc = r["PSV-C01"]
    assert calc["status"] == "NON_COMPLIANT"
    assert "Effective orifice area 2.853 in2 (page 2) is below the required effective area 3,699.0 mm2" \
        in calc["detail"]
    assert "API 520-I 5.6.3" in calc["detail"] and "molecular weight 51 (page 2)" in calc["detail"]
    assert calc["calculated_mm2"] == pytest.approx(3699.0, abs=0.1)


def test_an_orifice_at_least_the_calculated_area_meets_when_every_input_is_exact():
    r = results(GAS + [fact("orifice area", "6.38", "in2")])
    assert r["PSV-C01"]["status"] == "COMPLIANT"
    assert "is at least the required effective area" in r["PSV-C01"]["detail"]


@pytest.mark.parametrize("change, why", [
    (lambda s: _without(s, "valve type") + [fact("valve type", "Balanced bellows")],
     "not stated as conventional, so Kb was taken as 1.0"),
    (lambda s: _without(_without(s, "superimposed back pressure"), "built up back pressure"),
     "is not given (taken as 0), so critical flow was assumed"),
    (lambda s: _without(s, "built up back pressure") + [fact("built up back pressure", "4", "barg")],
     "subcritical"),
])
def test_a_lower_bound_area_is_never_a_pass(change, why):
    r = results(change(GAS) + [fact("orifice area", "6.38", "in2")])
    assert r["PSV-C01"]["status"] == "NEEDS_ENGINEER_REVIEW"
    assert why in r["PSV-C01"]["detail"]
    # ... but an orifice below even the lower bound is still a finding
    small = results(change(GAS) + [fact("orifice area", "2.853", "in2")])
    assert small["PSV-C01"]["status"] == "NON_COMPLIANT"


def test_the_sheets_own_required_area_is_checked_within_its_rounding():
    ok = results(GAS + [fact("required area", f"{3699 * 0.985:.1f}", "mm2", label="Calculated area")])
    low = results(GAS + [fact("required area", f"{3699 * 0.97:.1f}", "mm2", label="Calculated area")])
    assert ok["PSV-C02"]["status"] == "COMPLIANT" and "within 2% for rounding" in ok["PSV-C02"]["detail"]
    assert low["PSV-C02"]["status"] == "NON_COMPLIANT"


@pytest.mark.parametrize("facts, reason", [
    (_without(GAS, "molecular weight"), "the molecular weight is not given"),
    (_without(GAS, "set pressure") + [fact("set pressure", "5.7", "bar")],
     "the set pressure does not say gauge or absolute"),
    (_without(GAS, "required capacity") + [fact("required capacity", "500", "m3/h")],
     "the required capacity unit 'm3/h' is not one this calculation converts"),
    (_without(GAS, "fluid phase"), "the fluid phase is not stated, so the formula to use is not known"),
])
def test_a_missing_input_skips_the_calculation_with_its_reason(facts, reason):
    r = results(facts + [fact("orifice area", "2.853", "in2")])
    assert r["PSV-C01"]["status"] == dc.NOT_CALCULATED
    assert reason in r["PSV-C01"]["detail"].lower()


def test_a_set_pressure_unit_in_the_label_is_read():
    labelled = _without(GAS, "set pressure") + [
        fact("set pressure", f"{568.675 / 100:.5f}", label="Set pressure (barg)")]
    assert dc.api520_gas_area(_get(labelled), RULES)["area_mm2"] == pytest.approx(3698, rel=0.001)


def test_an_absolute_set_pressure_is_turned_into_gauge():
    absolute = _without(GAS, "set pressure") + [fact("set pressure", "670", "kPa(a)")]
    assert dc.api520_gas_area(_get(absolute), RULES)["area_mm2"] == pytest.approx(3698, rel=0.001)


def test_the_liquid_item_runs_for_liquid_and_the_gas_item_does_not():
    r = results(LIQUID + [fact("orifice area", "1.838", "in2")])
    assert r["PSV-C03"]["status"] == "NON_COMPLIANT"
    assert r["PSV-C01"]["status"] == "NOT_APPLICABLE"


def test_the_required_area_label_is_its_own_field():
    assert dc.role_of("required orifice area", RULES) == "required_area"
    assert dc.role_of("calculated area", RULES) == "required_area"
    assert dc.role_of("effective orifice area", RULES) == "orifice_area"


def test_not_calculated_is_never_written_and_never_counted_as_a_field(monkeypatch):
    written = []
    from app import review as review_mod
    monkeypatch.setattr(review_mod, "rejected_in_run", lambda *a, **k: [])
    monkeypatch.setattr(review_mod, "create", lambda row, created_by=None: written.append(row) or {"id": "x"})

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a): return self

    import app.db as db_mod
    monkeypatch.setattr(db_mod, "connect", lambda: _Conn())
    out = dc.evaluate(_without(GAS, "molecular weight"), equipment_type=PSV, page_texts={1: "x"})
    skipped = [r for r in out if r["status"] == dc.NOT_CALCULATED]
    assert skipped
    dc.store("run", "sub", skipped, pages_read={})
    assert written == []
    with_calc = dc.coverage(out)
    without_calc = dc.coverage([r for r in out if not r.get("calc")])
    assert with_calc == without_calc


@pytest.mark.parametrize("value, status", [("12", "NON_COMPLIANT"), ("8", "COMPLIANT")])
def test_built_up_back_pressure_stated_as_a_percentage_is_compared_as_one(value, status):
    sheet = [fact("set pressure", "10", "barg"), fact("valve type", "Conventional"),
             fact("back press variable", value, "%")]
    assert results(sheet)["PSV-29"]["status"] == status


@pytest.mark.parametrize("value, status, shown", [
    ("1.2", "NON_COMPLIANT", "12.0%"), ("0.9", "COMPLIANT", "9.0%")])
def test_overpressure_stated_as_a_pressure_is_worked_out_as_a_percentage(value, status, shown):
    sheet = [fact("set pressure", "10", "barg"), fact("relief case", "Blocked outlet"),
             fact("over pressure", value, "bar")]
    r = results(sheet)["PSV-28"]
    assert r["status"] == status and shown in r["detail"] and "set pressure 10 barg (page 2)" in r["detail"]


def test_an_overpressure_percentage_needs_a_gauge_set_pressure():
    sheet = [fact("set pressure", "10", "bar"), fact("relief case", "Blocked outlet"),
             fact("over pressure", "1.2", "bar")]
    r = results(sheet)["PSV-28"]
    assert r["status"] == "NEEDS_ENGINEER_REVIEW" and "gauge or absolute" in r["detail"]
