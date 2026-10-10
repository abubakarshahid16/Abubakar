"""match_rules rule 5: a pairing must not cross a qualifier.

Found on the real PSV review (2026-10-10, hand-check sheet): "the maximum
external design pressure" and "the operating pressure of the jacket" were
paired by whole-word containment with the sheet's plain design and operating
pressures, and gave seven false NON_COMPLIANT findings. A qualifier word in the
requirement's subject that the field name lacks now refuses the pairing (an
engineer's question, never a verdict). Invented values only.
"""
from __future__ import annotations

from app import comparison, match_rules


def _req(subject, value="15", unit="psi"):
    return {"id": "r", "requirement_type": "numeric_limit", "subject": subject,
            "requirement_text": f"{subject} shall not exceed {value} {unit}.",
            "operator": "<=", "raw_value": value, "raw_unit": unit}


def _fact(name, value="23.5", unit="barg"):
    return {"id": f"f-{name}", "field_name": name, "field_label": name.capitalize(),
            "field_value": f"{value} {unit}", "raw_value": value, "raw_unit": unit,
            "value": float(value), "is_blank": 0}


def test_a_qualifier_in_the_subject_that_the_field_lacks_refuses_the_pair():
    assert match_rules.qualifier_conflict(_req("the maximum external design pressure"), "design pressure")
    assert match_rules.qualifier_conflict(_req("the operating pressure of the jacket"), "operating pressure")
    # the field carries it too: no conflict
    assert not match_rules.qualifier_conflict(_req("the outlet pressure"), "outlet pressure")
    assert not match_rules.qualifier_conflict(_req("the external design pressure"), "external design pressure")
    # no qualifier at all: no conflict
    assert not match_rules.qualifier_conflict(_req("the design pressure"), "design pressure")
    assert not match_rules.qualifier_conflict(_req(""), "design pressure")


def test_the_pairing_is_refused_and_counted_under_its_reason():
    match = comparison.match_by_containment(_req("the maximum external design pressure"),
                                            [_fact("design pressure")])
    assert match["fact"] is None
    assert [r["reason"] for r in match["refused"]] == [match_rules.QUALIFIER]
    # the plain quantity still pairs, so nothing else is lost
    plain = comparison.match_by_containment(_req("the design pressure"), [_fact("design pressure")])
    assert plain["fact"] is not None and plain["fact"]["field_name"] == "design pressure"


def test_a_field_that_names_the_same_side_still_pairs():
    match = comparison.match_by_containment(_req("the outlet pressure", "10", "barg"),
                                            [_fact("outlet pressure", "8", "barg")])
    assert match["fact"] is not None and match["fact"]["field_name"] == "outlet pressure"


def test_a_qualifier_counts_only_next_to_the_fields_own_words():
    # "shell" qualifies the thickness here, not the pressure
    assert not match_rules.qualifier_conflict(
        _req("the minimum shell thickness and the maximum allowable working pressure"),
        "maximum allowable working pressure")
    # a nozzle is the item a field names, not a side of it
    assert not match_rules.qualifier_conflict(_req("nozzle size"), "size")
    # but "of the jacket" right after the field's words is a conflict
    assert match_rules.qualifier_conflict(_req("the design pressure of the shell"), "design pressure")
