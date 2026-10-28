"""Order 264.8: a Part limited to a construction is settled by a fact the datasheet STATES.

Invented sheets and standards. The model is the fake of test_141_division_scope; where a test says
"no model call", the Part was answered from the sheet by code alone."""

from __future__ import annotations

import pytest

from app import absence, ai_applicability, scope_construction
from tests.test_141_division_scope import (  # noqa: F401 - the fixture and the fake model
    GENERAL,
    PAGES,
    FakeModel,
    temp_storage,
)

CC_SCOPE = "The rules in Part CC are applicable to vessels constructed of carbon and low alloy steel."
WW_SCOPE = "The rules in Part WW are applicable to vessels of welded construction."
EXTRA_PAGES = [
    (
        4,
        "PART CC\nREQUIREMENTS FOR VESSELS CONSTRUCTED OF CARBON STEEL\nCC-1 SCOPE\n"
        + CC_SCOPE
        + "\nCC-2 The shell shall be tested at 1.5 times the design pressure.\n",
    ),
    (
        5,
        "PART WW\nREQUIREMENTS FOR WELDED VESSELS\nWW-1 SCOPE\n"
        + WW_SCOPE
        + "\nWW-2 Welds shall be examined over their full length.\n",
    ),
]
CARBON_RULE = {
    "id": "cc",
    "standard_document_id": "std",
    "page": 4,
    "requirement_text": "The shell shall be tested at 1.5 times the design pressure.",
    "source_text": "CC-2 The shell shall be tested at 1.5 times the design pressure.",
}
WELD_RULE = {
    "id": "ww",
    "standard_document_id": "std",
    "page": 5,
    "requirement_text": "Welds shall be examined over their full length.",
    "source_text": "WW-2 Welds shall be examined over their full length.",
}
LIMITED_CC = {
    "limited": "yes",
    "construction": "constructed of carbon and low alloy steel",
    "quote": CC_SCOPE,
}
LIMITED_WW = {
    "limited": "yes",
    "construction": "of welded construction",
    "quote": WW_SCOPE,
}


def _fact(label, value, page=2, fact_id="f1"):
    return {
        "id": fact_id,
        "field_name": label.lower(),
        "field_label": label,
        "field_value": value,
        "raw_value": value,
        "page": page,
    }


def _scope(prompt):
    if "Part CC" in prompt:
        return LIMITED_CC
    if "Part WW" in prompt:
        return LIMITED_WW
    return {"limited": "no", "construction": None, "quote": None}


def _gate(facts, reqs=(GENERAL, CARBON_RULE, WELD_RULE)):
    model = FakeModel(scope=_scope)
    out = ai_applicability.division_gate(
        [dict(r) for r in reqs],
        classification={"equipment_type": "Pressure vessel"},
        facts=facts,
        standard_labels={"std": "XYZ code"},
        provider=model,
        pages_of=lambda sid: [*PAGES, *EXTRA_PAGES],
    )
    return out, model


def _ids(rows):
    return [r["requirement"]["id"] if "requirement" in r else r["id"] for r in rows]


def test_a_carbon_steel_part_applies_when_the_shell_material_is_a_carbon_steel_plate(
    temp_storage,
):
    out, model = _gate(
        [_fact("Shell material", "SA-516 Gr 70", page=2)], reqs=(GENERAL, CARBON_RULE)
    )
    assert (
        _ids(out["kept"]) == ["aa", "cc"] and out["held"] == [] and out["items"] == []
    )
    assert (
        "construction" not in model.calls
    )  # answered by code from the sheet, no second model question
    [answered] = out["summary"]["answered_from_sheet"]
    assert answered["field"] == "Shell material" and answered["value"] == "SA-516 Gr 70"
    assert answered["page"] == 2 and answered["family"] == "carbon and low-alloy steel"


def test_a_stainless_sheet_does_not_settle_a_carbon_steel_part_and_nothing_is_excluded_by_it(
    temp_storage,
):
    out, model = _gate(
        [_fact("Shell material", "SA-240 Type 304 stainless")],
        reqs=(GENERAL, CARBON_RULE),
    )
    assert out["summary"].get("answered_from_sheet") == []
    assert (
        "construction" in model.calls
    )  # not settled: the model task and the engineer decide as before
    assert "cc" not in _ids(out["kept"]) or out["items"] == []


def test_a_layer_on_the_base_never_settles_it(temp_storage):
    facts = [_fact("Shell material", "SA-516 Gr 70 with stainless cladding")]
    out, _ = _gate(facts, reqs=(GENERAL, CARBON_RULE))
    assert out["summary"].get("answered_from_sheet") == []


def test_a_welded_part_applies_when_the_sheet_states_a_joint_efficiency(temp_storage):
    out, model = _gate(
        [_fact("Joint efficiency", "0.85", page=3)], reqs=(GENERAL, WELD_RULE)
    )
    assert _ids(out["kept"]) == ["aa", "ww"]
    assert "construction" not in model.calls
    assert out["summary"]["answered_from_sheet"][0]["page"] == 3


def test_a_material_in_another_field_does_not_settle_the_shell(temp_storage):
    out, _ = _gate(
        [_fact("Gasket material", "SA-516 Gr 70")], reqs=(GENERAL, CARBON_RULE)
    )
    assert out["summary"].get("answered_from_sheet") == []


def test_a_blank_field_settles_nothing(temp_storage):
    blank = {**_fact("Shell material", "SA-516 Gr 70"), "is_blank": 1}
    assert scope_construction.settle("carbon and low alloy steel", [blank]) is None
    assert (
        scope_construction.settle(
            "carbon and low alloy steel", [_fact("Shell material", "  ")]
        )
        is None
    )


@pytest.mark.parametrize(
    ("phrase", "family"),
    [
        (
            "vessels constructed of carbon and low alloy steel",
            "carbon and low-alloy steel",
        ),
        ("welded construction", "welded construction"),
        ("Vessels of FORGED construction", "forged construction"),
    ],
)
def test_the_words_of_the_phrase_name_the_family(phrase, family):
    facts = [
        _fact("Shell material", "SA-516 Gr 70"),
        _fact("Weld joint type", "double welded butt"),
        _fact("Forging note", "forged shell"),
    ]
    assert scope_construction.settle(phrase, facts)["family"] == family


@pytest.mark.parametrize(
    "phrase",
    ["vessels of brazed construction", "equipment of a particular kind", "", "steel"],
)
def test_a_phrase_no_family_names_settles_nothing(phrase):
    assert (
        scope_construction.settle(phrase, [_fact("Shell material", "SA-516 Gr 70")])
        is None
    )


def test_the_review_notes_say_what_the_sheet_settled_once_per_fact():
    item = {
        "construction": "carbon steel",
        "field": "Shell material",
        "value": "SA-516 Gr 70",
        "page": 2,
        "fact_id": "f1",
    }
    lines = absence.settled_scope_lines({"answered_from_sheet": [item, dict(item)]})
    assert lines == [
        "Answered from the datasheet: a Part limited to 'carbon steel' applies; "
        "Shell material states 'SA-516 Gr 70' (page 2)."
    ]
    assert (
        absence.settled_scope_lines(None) == []
        and absence.settled_scope_lines({}) == []
    )


def test_a_tube_or_a_seal_material_is_not_the_vessel(temp_storage):
    # a main part or only a component? Not for code to say: the shell and the heads settle a material
    facts = [
        _fact("Tube material", "Seamless titanium tubes"),
        _fact("Tube material", "SA-516 Gr 70", fact_id="f2"),
    ]
    assert scope_construction.settle("constructed of titanium", facts) is None
    assert scope_construction.settle("carbon and low alloy steel", facts) is None
