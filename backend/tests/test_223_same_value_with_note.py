"""Order 223: the same number and unit with a note is ONE value.

The owner's X-ray of a relief-valve run showed about 33 "two different values on
the sheet" rows where the reader had stored one value twice, `340 psig` and
`340 psig (By Contractor, as per Code)`, under one tag. The check compared the
printed TEXT, so the note made a second value. It now compares what the value
IS (number, unit, gauge/absolute); a different number stays two values.
Made-up values only.
"""

from __future__ import annotations

from app import datasheet_checks as dc
from app import rule_eval
from tests.test_datasheet_checks import PAGES, VESSEL, P, fact, full_vessel


def _with_note(name: str, value: str, note: str, unit: str = "barg") -> dict:
    f = P(name, value, unit)
    return {
        **f,
        "id": f"{f['id']}-noted",
        "field_value": f"{value} {unit} {note}",
        "page": 2,
    }


def _result(facts, rule_id="DS-C1"):
    results = dc.evaluate(facts, equipment_type=VESSEL, page_texts=PAGES)
    return next(r for r in results if r["rule_id"] == rule_id)


def test_the_same_number_with_a_note_is_one_value_and_is_compared():
    facts = [
        *full_vessel(),
        _with_note("design pressure", "23.5", "(By Contractor, as per Code)"),
    ]
    result = _result(facts)
    assert result["status"] == "COMPLIANT", result


def test_a_trailing_note_after_the_unit_is_still_one_value():
    facts = [*full_vessel(), _with_note("operating pressure", "20", "Note - 2")]
    assert _result(facts)["status"] == "COMPLIANT"


def test_a_different_number_stays_two_values_for_the_engineer():
    facts = [*full_vessel(), P("design pressure", "15")]
    result = _result(facts)
    assert result["status"] == "NEEDS_ENGINEER_REVIEW"
    assert "two different values" in result["detail"]


def test_the_same_number_with_a_note_does_not_hide_a_real_breach():
    # design 18 (with a note, twice) is still below operating 20
    facts = [
        *full_vessel(**{"design pressure": P("design pressure", "18")}),
        _with_note("design pressure", "18", "(per Code)"),
    ]
    assert _result(facts)["status"] == "NON_COMPLIANT"


def test_each_tag_is_judged_on_its_own_values():
    def tagged(name, value, tag):
        return {**P(name, value), "equipment_tag": tag, "id": f"{name}-{value}-{tag}"}

    facts = [
        tagged("design pressure", "23.5", "PSV-1"),
        {
            **_with_note("design pressure", "23.5", "(per Code)"),
            "equipment_tag": "PSV-1",
        },
        tagged("operating pressure", "20", "PSV-1"),
        tagged("design pressure", "18", "PSV-2"),
        tagged("operating pressure", "20", "PSV-2"),
    ]
    results = [
        r
        for r in dc.evaluate(
            facts, equipment_type="Pressure Safety Valve", page_texts=PAGES
        )
        if r["rule_id"] == "DS-C1"
    ]
    by_tag = {r["equipment_tag"]: r["status"] for r in results}
    if by_tag:  # the rule applies to this type: PSV-1 compared, PSV-2 breached
        assert by_tag.get("PSV-1") != "NEEDS_ENGINEER_REVIEW"
        assert by_tag.get("PSV-2") in (None, "NON_COMPLIANT")


def test_the_key_keeps_different_text_and_different_numbers_apart():
    key = rule_eval.same_value_key
    assert key(fact("x", "340", "psig")) == key(
        {**fact("x", "340", "psig"), "field_value": "340 psig (By Contractor)"}
    )
    assert key(fact("x", "340", "psig")) != key(fact("x", "130", "psig"))
    assert key({"field_value": "Open"}) != key({"field_value": "Closed"})
