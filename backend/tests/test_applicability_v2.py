"""Applicability v2 decision rule (owner order 2026-09-25, 4.5). Synthetic
lexicon and scope records - no client documents."""
import pytest

from app.applicability_v2 import (APPLICABLE, APPLICABLE_CANDIDATE, NOT_APPLICABLE, UNKNOWN,
                                  Profile, decide, nodes_for)

LEX = {
    "centrifugal pump": ("type", "Centrifugal Pump"),
    "pump": ("family", "Pumps"),
    "pressure vessel": ("family", "Pressure vessels"),
    "vessel": ("family", "Pressure vessels"),
    "heat exchanger": ("family", "Heat transfer"),
    "rotating equipment": ("class", "Rotating"),
    "static mechanical equipment": ("class", "Static / Mechanical"),
    "pressure relief valve": ("family", "Pressure relief devices"),
    "valve": ("class", "Pressure relief and valves"),
}
PUMP = Profile("Centrifugal Pump", "Pumps", "Rotating")
VESSEL = Profile("Pressure Vessel", "Pressure vessels", "Static / Mechanical",
                 numbers={"pressure": (0.35, 0.35, "MPa")})
PSV = Profile("Pressure Safety / Relief Valve", "Pressure relief devices", "Pressure relief and valves")


def item(term, quote="q", page=1, **kw):
    return {"term": term, "quote": quote, "page": page, **kw}


def rec(covered=(), exclusions=(), limits=(), generic=False):
    return {"covered_equipment": list(covered), "explicit_exclusions": list(exclusions),
            "explicit_limits": list(limits), "generic_scope": generic}


# ------------------------------------------------------------ term matching

def test_a_longer_phrase_is_not_also_counted_as_its_shorter_part():
    assert nodes_for("pressure relief valves", LEX) == {("family", "Pressure relief devices")}


def test_whole_words_only():
    assert nodes_for("pumping station", LEX) == set()


# ------------------------------------------------------------------ APPLICABLE

def test_covered_family_names_the_submittal():
    r = decide(rec(covered=[item("pressure vessels", "applies to pressure vessels", 3)]), VESSEL, LEX)
    assert r["decision"] == APPLICABLE and r["quote"] == "applies to pressure vessels" and r["page"] == 3


def test_covered_class_names_the_submittal_by_taxonomy_not_by_model():
    """The v1 error: the model called a pump static. Here code knows a pump
    is Rotating, so 'static mechanical equipment' does NOT cover it."""
    r = decide(rec(covered=[item("process static mechanical equipment")]), PUMP, LEX)
    assert r["decision"] == UNKNOWN
    assert decide(rec(covered=[item("process static mechanical equipment")]), VESSEL, LEX)["decision"] == APPLICABLE


# -------------------------------------------------- NOT_APPLICABLE needs evidence

def test_a_vessel_only_scope_does_not_make_a_pump_not_applicable_by_itself():
    """THE MUTATION TARGET (M560): listing other equipment is UNKNOWN."""
    r = decide(rec(covered=[item("pressure vessels")]), PUMP, LEX)
    assert r["decision"] == UNKNOWN


def test_a_pump_is_not_applicable_only_with_an_equipment_limit_quote():
    r = decide(rec(covered=[item("pressure vessels")],
                   limits=[item("pressure vessels", "applies only to pressure vessels", 2, kind="equipment")]),
               PUMP, LEX)
    assert r["decision"] == NOT_APPLICABLE
    assert r["quote"] == "applies only to pressure vessels" and r["page"] == 2


def test_an_exclusion_naming_the_family_is_not_applicable():
    r = decide(rec(covered=[item("rotating equipment")],
                   exclusions=[item("centrifugal pumps", "does not cover centrifugal pumps", 4)]), PUMP, LEX)
    assert r["decision"] == NOT_APPLICABLE and r["basis"].startswith("explicit exclusion")


def test_an_exclusion_of_something_else_does_not_exclude_the_submittal():
    r = decide(rec(covered=[item("pressure vessels")], exclusions=[item("heat exchangers")]), VESSEL, LEX)
    assert r["decision"] == APPLICABLE


def test_an_item_without_a_quote_never_decides():
    """THE MUTATION TARGET (M561)."""
    r = decide(rec(covered=[item("pressure vessels")],
                   limits=[item("pressure vessels", quote=None, kind="equipment")]), PUMP, LEX)
    assert r["decision"] == UNKNOWN


# ---------------------------------------------------------- generic scope

def test_generic_scope_never_yields_not_applicable():
    """THE MUTATION TARGET (M562): a generic scope with a limit the
    submittal is outside of is still not NOT_APPLICABLE."""
    r = decide(rec(covered=[item("equipment")], generic=True,
                   limits=[item("pressure vessels", kind="equipment"),
                           item("pressure", kind="pressure", min=10, unit="MPa")]), PUMP, LEX)
    assert r["decision"] == APPLICABLE_CANDIDATE


def test_generic_scope_with_an_exclusion_naming_the_submittal_is_not_applicable():
    r = decide(rec(covered=[item("equipment")], generic=True,
                   exclusions=[item("pressure relief valves", "excluding pressure relief valves")]), PSV, LEX)
    assert r["decision"] == NOT_APPLICABLE


# ----------------------------------------------------------- numbers by code

@pytest.mark.parametrize("limit,expected", [
    ({"min": 1.0, "unit": "MPa"}, NOT_APPLICABLE),     # vessel 0.35 MPa is below
    ({"min": 15, "unit": "psig"}, APPLICABLE),         # 15 psig = 0.103 MPa, vessel above
    ({"max": 3, "unit": "bar"}, NOT_APPLICABLE),       # 0.3 MPa max, vessel 0.35 above
    ({"min": 1.0, "unit": "furlongs"}, APPLICABLE),    # unknown unit: no decision by number
])
def test_pressure_limits_are_compared_by_code(limit, expected):
    """THE MUTATION TARGET (M563) for the unit conversion."""
    r = decide(rec(covered=[item("pressure vessels")],
                   limits=[item("design pressure", kind="pressure", **limit)]), VESSEL, LEX)
    assert r["decision"] == expected


def test_an_unknown_submittal_number_never_decides():
    r = decide(rec(covered=[item("centrifugal pumps")],
                   limits=[item("design pressure", kind="pressure", min=10, unit="MPa")]), PUMP, LEX)
    assert r["decision"] == APPLICABLE


def test_no_record_is_unknown():
    assert decide(None, PUMP, LEX)["decision"] == UNKNOWN
