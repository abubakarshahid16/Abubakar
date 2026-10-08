"""Unit tests for `app.field_links` - synonym rewriting, nozzle-mark fields,
and closed categorical comparison. CRS quick wins (audit crs.md defect 3).

Standalone, no db.
"""
from __future__ import annotations

from app import field_links


def test_synonym_is_rewritten_to_its_canonical_phrase():
    """THE MUTATION TARGET (M1305): "hydrostatic test pressure" (the clause's
    words) and "HYDROTEST PRESSURE" (the sheet's own words) fold to the same
    phrase, so the pairing that never happened (audit crs.md defect 3) can."""
    assert field_links.canonical("hydrostatic test pressure") == field_links.canonical(
        "HYDROTEST PRESSURE")
    assert "hydrotest" in field_links.canonical("hydrostatic test pressure")


def test_a_word_with_no_synonym_entry_is_only_folded_not_rewritten():
    assert field_links.canonical("shell thickness") == "shell thickness"


def test_nozzle_mark_field_reads_as_the_nozzle_attribute_with_its_item():
    """THE MUTATION TARGET (M1306): "N3 SIZE" is the nozzle's size field, not
    a field of its own that a clause about "nozzle size" could never meet."""
    field, item = field_links.field_of("N3 SIZE")
    assert field == "nozzle size"
    assert item == "N3"


def test_a_plain_field_name_carries_no_item():
    field, item = field_links.field_of("Corrosion allowance")
    assert field == "corrosion allowance"
    assert item is None


def test_flange_class_requirement_is_read_as_a_minimum():
    """THE MUTATION TARGET (M1307): "minimum pressure rating of Class 300"
    is `{family: flange_rating, operator: >=, value: 300}` - a categorical
    quantity a datasheet's CL150/CL300 answer can be checked against, without
    ever being forced through the numeric comparator (CL150 is not a number)."""
    rule = field_links.categorical_requirement(
        "Nozzle flanges shall have a minimum pressure rating of Class 300.")
    assert rule == {"family": "flange_rating", "operator": ">=", "value": 300,
                    "shown": "Class 300", "condition": None}


def test_cl150_fails_a_minimum_class_300_requirement():
    """THE MUTATION TARGET (M1308): the audit's planted N2 flange breach
    (CL150 against a Class 300 minimum) is a categorical NON_COMPLIANT, not a
    silent non-match because neither side is a number."""
    rule = field_links.categorical_requirement(
        "minimum pressure rating of Class 300")
    verdict = field_links.compare_categorical(rule, "CL150")
    assert verdict["status"] == "NON_COMPLIANT"
    verdict_ok = field_links.compare_categorical(rule, "CLASS 300")
    assert verdict_ok["status"] == "COMPLIANT"


def test_a_conditional_categorical_clause_is_a_question_never_a_verdict():
    """A clause phrased "for vessels in sour service" is never decided here:
    the datasheet does not say whether the vessel is in sour service."""
    rule = field_links.categorical_requirement(
        "Full radiography shall be performed on all butt welds of vessels "
        "in sour service.")
    assert rule["condition"]
    verdict = field_links.compare_categorical(rule, "SPOT")
    assert verdict["status"] == "NEEDS_ENGINEER_REVIEW"


def test_a_free_text_answer_is_never_guessed_into_a_class():
    rule = field_links.categorical_requirement("minimum pressure rating of Class 300")
    assert field_links.compare_categorical(rule, "SEE DRAWING") is None
