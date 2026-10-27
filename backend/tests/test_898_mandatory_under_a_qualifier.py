"""#898 (PF2): a mandatory field the sheet states under a leading qualifier is
not reported as "not found".

PF1's first run (#881): four invented sheets printing "Casing design
pressure" or "Shell-side design temperature" were told "Design pressure was
not found in the fields read". The other twelve "missing" findings of that
run were TRUE - those sheets really lack the field - and stay.

Not "missing", and not silent either: code does not decide that the casing's
design pressure is THE design pressure. The finding becomes an engineer's
question that names the row. A qualified field is never used in a comparison.
Invented data only.
"""
from __future__ import annotations

import pytest

from app import datasheet_checks as dc
from tests.test_datasheet_checks import fact

RULES = dc.load_rules()


def _mandatory(results, role):
    return [r for r in results if r["rule_id"] == "DS-M1" and r["role"] == role]


@pytest.mark.parametrize("name, role", [
    ("Casing design pressure", "design_pressure"),
    ("Shell side design temperature", "design_temperature"),
    ("shell-side design temperature", "design_temperature"),
    ("Tube bundle hydrostatic test pressure", "test_pressure"),
    ("Jacket corrosion allowance", "corrosion_allowance"),
])
def test_a_role_under_a_leading_qualifier(name, role):
    assert dc.qualified_role_of(name, RULES) == role


@pytest.mark.parametrize("name", [
    "Design pressure",                         # the role itself: not "qualified"
    "Design pressure note",                    # a trailing word makes it another thing
    "Minimum design metal temperature",        # not a design temperature
    "Lube oil system design pressure",         # three leading words: too far
    "Remarks", "Pressure", "",
])
def test_what_is_not_a_qualified_role(name):
    assert dc.qualified_role_of(name, RULES) is None


def test_a_field_stated_under_a_qualifier_is_an_engineers_question_that_names_the_row():
    """THE CASE of PF1's pump sheet."""
    results = dc.evaluate([fact("casing design pressure", "14", "barg"), fact("design temperature", "150", "°C"),
                           fact("rated flow", "100", "m3/h"), fact("operating temperature", "60", "°C")],
                          equipment_type="Centrifugal Pump", page_texts={}, rules=RULES)
    (found,) = _mandatory(results, "design_pressure")
    assert found["status"] == dc.NEEDS_ENGINEER_REVIEW
    assert "'Casing design pressure' (page 1)" in found["detail"] and "not found under that name" in found["detail"]
    assert found["value"] == "14 barg" and found["page"] == 1 and found["fact_id"]
    # the mandatory check only: the pump checklist (order 235.2) asks for more fields
    assert not [
        r
        for r in results
        if r["status"] == dc.MISSING_INFORMATION and not r.get("checklist")
    ]


def test_a_field_the_sheet_does_not_state_at_all_is_still_missing():
    results = dc.evaluate([fact("design temperature", "150", "°C"), fact("seal plan", "11")],
                          equipment_type="Centrifugal Pump", page_texts={}, rules=RULES)
    (found,) = _mandatory(results, "design_pressure")
    assert found["status"] == dc.MISSING_INFORMATION and "was not found in the fields read" in found["detail"]


def test_a_field_stated_plainly_wins_and_nothing_is_said():
    results = dc.evaluate([fact("design pressure", "16", "barg"), fact("casing design pressure", "14", "barg"),
                           fact("design temperature", "150", "°C"), fact("rated flow", "100", "m3/h"),
                           fact("operating temperature", "60", "°C")], equipment_type="Centrifugal Pump", page_texts={}, rules=RULES)
    assert _mandatory(results, "design_pressure") == []


def test_a_blank_qualified_field_does_not_count_as_stated():
    results = dc.evaluate([fact("casing design pressure", None, blank="TBA"), fact("design temperature", "150", "°C")],
                          equipment_type="Centrifugal Pump", page_texts={}, rules=RULES)
    (found,) = _mandatory(results, "design_pressure")
    assert found["status"] == dc.MISSING_INFORMATION


def test_a_qualified_field_is_never_used_in_a_comparison_or_a_unit_check():
    """The shell side's design pressure against the tube side's operating
    pressure is not a check; a qualified field has no role."""
    results = dc.evaluate([fact("casing design pressure", "5", "barg"), fact("operating pressure", "9", "barg"),
                           fact("shell side design temperature", "200")], equipment_type="Pressure Vessel", page_texts={}, rules=RULES)
    assert not [r for r in results if r["rule_id"].startswith("DS-C")]
    assert not [r for r in results if r["rule_id"].startswith("DS-U")]


def test_two_qualified_fields_are_both_named():
    results = dc.evaluate([fact("shell side design pressure x", "1"),          # not qualified: a trailing word
                           fact("jacket design temperature", "200", "°C"),
                           fact("coil design temperature", "250", "°C", page=2),
                           fact("design pressure", "10", "barg"), fact("test pressure", "15", "barg")],
                          equipment_type="Heat Exchanger", page_texts={}, rules=RULES)
    (found,) = _mandatory(results, "design_temperature")
    assert "'Coil design temperature' (page 2)" in found["detail"]
    assert "'Jacket design temperature' (page 1)" in found["detail"]


def test_a_tags_own_qualified_field_and_the_common_sections():
    """A two-pump sheet: the common section states the casing design
    pressure once; each pump is then asked the question, not told 'missing'."""
    results = dc.evaluate([fact("casing design pressure", "14", "barg"),
                           fact("rated flow", "100", "m3/h", tag="P-1"), fact("rated flow", "90", "m3/h", tag="P-2"),
                           fact("design temperature", "150", "°C"), fact("operating temperature", "60", "°C")],
                          equipment_type="Centrifugal Pump", page_texts={}, rules=RULES)
    found = _mandatory(results, "design_pressure")
    assert found and all(r["status"] == dc.NEEDS_ENGINEER_REVIEW for r in found)
