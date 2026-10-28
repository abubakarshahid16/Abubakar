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

pytestmark = pytest.mark.usefixtures("temp_storage")

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


def test_a_carbon_steel_part_applies_when_the_shell_material_is_a_carbon_steel_plate():
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


def test_a_stainless_sheet_does_not_settle_a_carbon_steel_part_and_nothing_is_excluded_by_it():
    out, model = _gate(
        [_fact("Shell material", "SA-240 Type 304 stainless")],
        reqs=(GENERAL, CARBON_RULE),
    )
    assert out["summary"].get("answered_from_sheet") == []
    assert (
        "construction" in model.calls
    )  # not settled: the model task and the engineer decide as before
    assert "cc" not in _ids(out["kept"]) or out["items"] == []


def test_a_layer_on_the_base_never_settles_it():
    facts = [_fact("Shell material", "SA-516 Gr 70, rubber lined")]
    out, _ = _gate(facts, reqs=(GENERAL, CARBON_RULE))
    assert out["summary"].get("answered_from_sheet") == []
    assert scope_construction.settle("carbon and low alloy steel", facts) is None
    clad = [_fact("Shell material", "SA-516 Gr 70 with 316L cladding")]
    assert scope_construction.settle("carbon and low alloy steel", clad) is None


def test_a_welded_part_applies_when_a_shell_or_design_code_value_states_welded():
    out, model = _gate(
        [_fact("Design code", "ASME VIII Div 1, welded construction", page=3)],
        reqs=(GENERAL, WELD_RULE),
    )
    assert _ids(out["kept"]) == ["aa", "ww"]
    assert "construction" not in model.calls
    assert out["summary"]["answered_from_sheet"][0]["page"] == 3


def test_a_material_in_another_field_does_not_settle_the_shell():
    out, _ = _gate(
        [_fact("Gasket material", "SA-516 Gr 70")], reqs=(GENERAL, CARBON_RULE)
    )
    assert out["summary"].get("answered_from_sheet") == []


def test_a_blank_field_settles_nothing():
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
        _fact("Shell material", "SA-516 Gr 70 forged shell"),
        _fact("Design code", "ASME VIII, welded"),
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


def test_a_tube_or_a_seal_material_is_not_the_vessel():
    # a main part or only a component? Not for code to say: the shell and the heads settle a material
    titanium_tube = [_fact("Tube material", "Seamless titanium tubes")]
    assert scope_construction.settle("constructed of titanium", titanium_tube) is None
    carbon_tube = [_fact("Tube material", "SA-516 Gr 70")]
    assert scope_construction.settle("carbon and low alloy steel", carbon_tube) is None


def test_a_fact_with_no_page_settles_nothing_no_claim_without_a_resolving_page():
    undated = {**_fact("Shell material", "SA-516 Gr 70"), "page": None}
    assert scope_construction.settle("carbon and low alloy steel", [undated]) is None


def test_welding_wording_in_a_tube_joint_or_a_seal_is_not_the_vessel_being_welded():
    facts = [
        _fact("Tube to tubesheet joint", "welded and expanded"),
        _fact("Seal type", "welded bellows"),
        _fact("Gasket", "spiral wound, welded ring"),
    ]
    assert scope_construction.settle("welded construction", facts) is None
    assert scope_construction.settle("of forged construction", facts) is None


def test_a_sheet_naming_a_carbon_shell_and_stainless_tubes_settles_the_carbon_part_and_never_the_stainless_one():
    facts = [
        _fact("Shell material", "SA-516 Gr 70", fact_id="f1"),
        _fact("Tube material", "SA-213 TP304 stainless", fact_id="f2"),
    ]
    assert (
        scope_construction.settle("carbon and low alloy steel", facts)["fact_id"]
        == "f1"
    )
    assert scope_construction.settle("high alloy steel", facts) is None


# ----------------------------------------------- cloud-2's three findings on #1409


@pytest.mark.parametrize(
    ("phrase", "label", "value"),
    [
        ("welded construction", "Shell material", "SA-106 Gr B seamless, not welded"),
        ("forged construction", "Head material", "not forged, formed plate SA-516-70"),
        ("welded construction", "Shell material", "non-welded seamless pipe"),
        ("welded construction", "Shell material", "seamless, without any welding"),
    ],
)
def test_a_negated_hit_settles_nothing(phrase, label, value):
    assert scope_construction.settle(phrase, [_fact(label, value)]) is None


def test_a_negation_far_from_the_hit_does_not_hide_it():
    fact = _fact(
        "Design code",
        "No exceptions taken to the code; vessel is a welded construction",
    )
    assert scope_construction.settle("welded construction", [fact]) is not None


@pytest.mark.parametrize("value", ["N/A", "0.85", "1.0", "per code"])
def test_a_joint_efficiency_says_nothing_about_welding_by_itself(value):
    assert (
        scope_construction.settle(
            "welded construction", [_fact("Joint efficiency", value)]
        )
        is None
    )
    assert (
        scope_construction.settle("welded construction", [_fact("PWHT", "Required")])
        is None
    )


def test_the_label_never_settles_only_the_value_does():
    assert (
        scope_construction.settle(
            "welded construction", [_fact("Welded joint type", "see drawing")]
        )
        is None
    )


@pytest.mark.parametrize(
    "facts",
    [
        # a stainless shell with a carbon head is mixed
        [
            _fact("Shell material", "SA-240 316L", fact_id="f1"),
            _fact("Head material", "SA-516-70", fact_id="f2"),
        ],
        # one value naming two families
        [_fact("Shell material", "Stainless steel 316L, carbon steel supports")],
    ],
)
def test_a_mixed_vessel_settles_no_material_family(facts):
    assert scope_construction.settle("carbon and low alloy steel", facts) is None
    assert scope_construction.settle("high alloy steel", facts) is None


def test_two_facts_of_one_family_agree_and_the_first_is_named():
    facts = [
        _fact("Shell material", "SA-516-70", fact_id="f1", page=2),
        _fact("Head material", "SA-516-70", fact_id="f2", page=3),
    ]
    got = scope_construction.settle("carbon and low alloy steel", facts)
    assert got["fact_id"] == "f1" and got["page"] == 2


def test_a_process_family_is_not_made_mixed_by_a_material():
    facts = [
        _fact("Shell material", "SA-516-70 welded plate", fact_id="f1"),
        _fact("Head material", "SA-240 316L", fact_id="f2"),
    ]
    # the welding is stated; the materials are mixed, which blocks only the material Parts
    assert (
        scope_construction.settle("welded construction", facts)["family"]
        == "welded construction"
    )
    assert scope_construction.settle("carbon and low alloy steel", facts) is None
