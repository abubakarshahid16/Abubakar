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
    assert BM.states_value(
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
