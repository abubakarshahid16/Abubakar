"""A line never asks the contractor to state a value the paper states (planner, 26 Nov 2026; #1887 shape): when the judge flags a
value as left open but the VERIFIED quote states it, code does not treat it as open. By the quote's structure only, never the AI's
words. Invented values only."""

from __future__ import annotations

from app import blank_markers as BM
from app.aim_review import steps as S


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


def test_a_value_the_judge_flagged_open_but_the_quote_states_is_not_left_open_and_says_so():
    notes: list[str] = []
    assert (
        S._left_open(
            {"deferred": True, "field": "Inlet size"}, "Inlet size: 4 in", 1, notes
        )
        is False
    )
    assert notes == [BM.STATED_NOT_OPEN]
    assert (
        S._ask({"deferred": True}, "Question", False, None, None) != S.ASK_OPEN
    )  # so never "please state"


def test_a_value_really_left_open_stays_open_and_an_unverified_quote_is_not_trusted():
    notes: list[str] = []
    assert (
        S._left_open(
            {"deferred": True, "field": "Inlet size"}, "Inlet size: TBA", 1, notes
        )
        is True
        and notes == []
    )
    assert (
        S._left_open(
            {"deferred": True, "field": "Inlet size"}, "Inlet size: 4 in", None, notes
        )
        is True
    )  # no verified page
    assert (
        S._left_open(
            {"deferred": False, "field": "Inlet size"}, "Inlet size: 4 in", 1, []
        )
        is False
    )  # unchanged
