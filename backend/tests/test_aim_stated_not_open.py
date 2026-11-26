"""A value the judge flags as left open is a Question, in every case (owner: a value left to the vendor is a Question, never Pass or
Fail). Update 13's always-on stated-value rule was taken out after its third review round (lead-4, 26 Nov 2026, review of update 13
B1); these guards hold main's behaviour. `blank_markers.states_value` stays only for the required-entries filter (switch off).
Invented values only."""

from __future__ import annotations

import pytest

from app import blank_markers as BM
from app.aim_review import steps as S
from tests.test_aim_local_fixes import ANSWER, ITEM, PAPER


def test_a_quote_that_names_the_field_and_holds_a_value_states_it():
    assert BM.states_value("Inlet size: 4 in", "Inlet size")
    # strict (lead-4, 26 Nov 2026, after the review of update 13, B1): a text value with no figure no longer counts as stated; a
    # "no" leaves the line as main has it (the required-entries filter then sends it)
    assert not BM.states_value(
        "12   Body material   carbon steel to the buyer list", "Body material"
    )


def test_a_blank_an_open_marker_or_a_quote_naming_another_field_states_nothing():
    assert not BM.states_value("Inlet size", "Inlet size")  # the label only
    assert not BM.states_value("Inlet size: TBA", "Inlet size")
    assert not BM.states_value("Inlet size: By Vendor", "Inlet size")
    assert not BM.states_value(
        "Outlet rating: Class 150", "Inlet size"
    )  # not this field
    assert not BM.states_value(
        "Set pressure barg", "Set pressure"
    )  # a label and its unit: no value
    assert not BM.states_value("", "Inlet size") and not BM.states_value(
        "Inlet size: 4 in", ""
    )


NUMS = {"paper_value": "1.5", "paper_unit": "mm", "operator": ">=", "rule_value": "3", "rule_unit": "mm"}  # fmt: skip
SHEET = "Invented sheet.\nCorrosion allowance (pressure parts): 1.5 mm\n"


@pytest.mark.parametrize(
    "value",
    [
        "1.5 mm",
        "VENDOR",
        "MFR STD",
        "per vendor",
        "see note 3",
        "(Note 2)",
        "pending",
        "not specified",
        "unknown",
        "",
        "By Vendor",
    ],
)
@pytest.mark.parametrize("label", ["Question", "Met", "Not met"])
@pytest.mark.parametrize("on_page", [True, False])
def test_a_value_the_judge_flags_left_open_is_a_question_with_no_verdict_from_code_on_both_routes(
    value, label, on_page
):
    """Every shape the review of update 13 found (a stated figure, who-supplies words, note pointers, "pending", "not specified",
    "unknown", a blank field), with each judge label, the quote on its page or not: a Question to the vendor, no code verdict."""
    from app.aim_review import budget
    from app.aim_review.paper import Paper

    quote = f"Corrosion allowance (pressure parts): {value}".strip()
    paper = Paper(
        paper_id="doc_inv_sheet",
        pages={
            2: f"Invented sheet.\n{quote}\nDesign pressure: 20 barg\n"
            if on_page
            else SHEET
        },
    )
    answer = {
        **ANSWER,
        "label": label,
        "quote": quote,
        "deferred": True,
        "numbers": NUMS,
    }
    with budget.using(budget.LOCAL):
        local = S._decide(ITEM, dict(answer), paper, {}, "")
    on_claude = S._decide(ITEM, dict(answer), paper, {}, "")
    for line in (local, on_claude):
        assert line["label"] == "Question" and not line["code_compare"]
        assert line["deferred"] is True and line["ask"] in (
            S.ASK_OPEN,
            S.ASK_CONCERN,
        )  # never "confirm"


def test_the_control_a_stated_value_not_flagged_open_is_still_compared_by_code():
    assert (
        S._decide(ITEM, {**ANSWER, "numbers": NUMS}, PAPER, {}, "")["label"]
        == "Not met"
    )
    assert not hasattr(BM, "stated_despite") and not hasattr(
        BM, "STATED_NOT_OPEN"
    )  # the always-on rule is out


@pytest.mark.parametrize(
    "value",
    ["VENDOR", "MFR STD", "per vendor", "see note 3", "(Note 2)", "pending", "not specified", "unknown", "", "By Vendor", "TBA",
     "N/A", "refer to note 2", "see attached", "as per spec", "later stage", "3 Note 2", "(see note 3) 3 mm", "carbon steel",
     "57   Drain pan elbow", "12/ZQ/004"],
)  # fmt: skip
def test_the_strict_check_states_nothing_for_any_shape_the_review_found_or_the_stored_runs_showed(
    value,
):
    """Every shape the review of update 13 found, a text value, and the two shapes the stored runs showed as false hits: a blank
    field followed by the next row's number and label, and a standard's identifier as a basis. Invented values."""
    assert not BM.states_value(
        f"Corrosion allowance: {value}".strip(), "Corrosion allowance"
    )


@pytest.mark.parametrize(
    "value",
    ["1.5 mm", "3 mm", ">= 3 mm", "2 x 50%", "0.125 in", "3", "1.5 mm (min)", "50%"],
)
def test_the_strict_check_states_a_plain_figure_and_its_unit_directly_after_the_label(
    value,
):
    assert BM.states_value(f"Corrosion allowance: {value}", "Corrosion allowance")
    assert BM.states_value(
        f"Corrosion allowance (pressure parts): {value}", "Corrosion allowance"
    )


def test_a_blank_field_beside_a_neighbours_figure_states_nothing():
    assert not BM.states_value(
        "Corrosion allowance:    Design pressure: 20 barg", "Corrosion allowance"
    )
    assert not BM.states_value(
        "Corrosion allowance - Design pressure 20 barg", "Corrosion allowance"
    )


def test_n7_the_required_entries_filter_sends_a_vendor_or_pointer_entry_and_holds_back_only_a_stated_figure(
    monkeypatch,
):
    """Review of update 13, N7: the switched-off G3 filter (`asks.entry_filled`) read the loose check, so a G3 line whose entry
    says "VENDOR" or "see note 3" would not have been sent. With the strict check it is sent; only a stated figure is held back."""
    from app.aim_review import asks
    from app.config import settings

    monkeypatch.setattr(settings, "aim_u13_enabled", True)
    line = {
        "item_id": "G3",
        "label": "Question",
        "field": "Corrosion allowance",
        "page": 2,
        "ask": "concern",
    }
    for open_entry in ("VENDOR", "see note 3", "not specified", "57   Drain pan elbow"):
        assert not asks.entry_filled(
            dict(line, quote=f"Corrosion allowance: {open_entry}")
        ), open_entry
    assert asks.entry_filled(dict(line, quote="Corrosion allowance: 3 mm"))
