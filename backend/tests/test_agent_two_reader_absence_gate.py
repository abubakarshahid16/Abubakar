"""The gates of the absence decision "AI verdict: not stated" (lead, 12 Nov 2026): each condition alone stops the word, and a rule the
code cannot search still earns it, saying so. Invented paper and rule; no network; the code's search is the real `prove_field`."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

from app import agent_review_absence as A
from app import agent_review_two_reader as two
from app import crs_ai_words as words
from app.config import settings
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_two_reader import CLASS
from tests.test_agent_two_reader_absence import (
    NOT_STATED,
    PAGES,
    ROLE,
    absence_step,
    both,  # noqa: F401
    paper,
    setup,
)


def _setup_with(w, **item_changes):
    fake = setup(w)
    for it in w["doc"]["items"]:
        if it["item_id"] == "R-coat":
            it.update(item_changes)
    return fake


@pytest.mark.parametrize(
    "changes",
    [
        {"rule_exceptions": '[{"when": "invented"}]'},  # a stored exception
        {"rule_kind": "advice"},  # advice
        {
            "requirement_type": "numeric_limit",
            "rule_condition": "when hot",
        },  # conditional
        {"rule_row_found": False},  # no stored rule row read
    ],
)
def test_a_rule_that_is_conditional_has_an_exception_or_is_advice_never_gets_the_word_and_nothing_is_asked(
    w, both, changes
):
    paper()
    fake = _setup_with(w, **changes)
    run_id = run_review()
    assert lines_of(run_id)["R-coat"]["word"] != NOT_STATED
    assert fake.absence_bodies == [] and absence_step(run_id)["asked"] == 0


def test_a_value_the_code_finds_on_any_page_vetoes_the_word_and_nothing_is_asked(
    w, both
):
    pages = {**PAGES, 3: PAGES[3] + "\nDesign pressure: 12 barg"}
    paper(pages)
    fake = _setup_with(w)
    run_id = run_review()
    assert (
        lines_of(run_id)["R-coat"]["word"] != NOT_STATED and fake.absence_bodies == []
    )
    assert absence_step(run_id)["skipped"] == 1


def test_a_label_with_an_empty_cell_does_not_veto_and_the_sentence_says_the_code_searched(
    w, both
):
    pages = {**PAGES, 3: PAGES[3] + "\nDesign pressure  ____"}
    paper(pages)
    _setup_with(w)
    run_id = run_review()
    got = lines_of(run_id)["R-coat"]
    assert (got["verdict_class"], got["word"]) == (CLASS, NOT_STATED)


def test_a_rule_with_no_known_field_still_gets_the_word_and_the_sentence_says_the_code_could_not_check(
    w, both
):
    paper()
    fake = _setup_with(w, field_roles=[], page_hint=[1, 2, 3])
    run_id = run_review()
    got = lines_of(run_id)["R-coat"]
    assert (got["verdict_class"], got["word"]) == (CLASS, NOT_STATED) and len(
        fake.absence_bodies
    ) == 1
    from tests.test_agent_two_reader import stored

    assert (
        stored(run_id, "R-coat")["two_reader_absence"]["code_check"]
        == two.CHECK_COULD_NOT
    )
    assert words.ABSENCE_CHECK_COULD_NOT in words.absence_verdict_sentence(
        "x", "y", False
    )
    assert words.ABSENCE_CHECK_SEARCHED in words.absence_verdict_sentence(
        "x", "y", True
    )


def test_a_paper_of_more_than_eight_pages_is_not_awarded_and_nothing_is_asked(w, both):
    pages = {
        n: f"Page {n}. Invented filler text about the casing, carbon steel to an invented grade."
        for n in range(1, 10)
    }
    paper(pages)
    fake = _setup_with(w, page_hint=list(range(1, 10)))
    run_id = run_review()
    assert (
        lines_of(run_id)["R-coat"]["word"] != NOT_STATED and fake.absence_bodies == []
    )
    assert absence_step(run_id)["off"] == two.OFF_PAPER_TOO_LONG


def test_the_switch_off_gives_no_word_and_no_call(w, monkeypatch):
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    monkeypatch.setattr(settings, "agent_review_two_reader_absence_enabled", False)
    monkeypatch.setattr(A, "carried_roles", lambda *_a, **_k: frozenset({ROLE}))
    paper()
    fake = _setup_with(w)
    run_id = run_review()
    assert (
        lines_of(run_id)["R-coat"]["word"] != NOT_STATED and fake.absence_bodies == []
    )


def test_a_checklist_item_is_plain_unless_its_text_is_conditional_or_advice():
    item = {"source": "skill", "item_id": "S-1"}
    assert A.plain_requirement_code(item, "Nameplate material of construction") is None
    assert (
        A.plain_requirement_code(item, "Nameplate should be steel")
        == "absence_not_binding"
    )
    assert (
        A.plain_requirement_code(item, "Where fitted, the nameplate is steel")
        == "absence_conditional"
    )
    assert (
        A.plain_requirement_code(
            {**item, "rule_exceptions": "[1]"}, "Nameplate material"
        )
        == "absence_exception"
    )
    assert A.plain_requirement_code(item, "") == "absence_rule_not_found"


def test_the_two_readers_page_lists_and_the_item_name_reach_the_sentence_only_through_the_one_home():
    sentence = words.absence_verdict_sentence(
        "Design pressure", "The nameplate shall be steel", True
    )
    assert sentence.startswith(
        f"{words.ABSENCE_OPENER}: two AI readers each read every page of the paper and found no Design pressure."
    )
    assert "quotes verified" not in sentence and sentence.endswith(
        "Engineer to confirm."
    )


def test_a_not_stated_line_is_a_decision_and_the_notes_say_of_which_not_stated_on_the_paper(
    tmp_path,
):
    import openpyxl

    from app import agent_review_wording as W
    from app import crs_ai_workbook as WB
    from tests.test_agent_review_crs import META
    from tests.test_agent_two_reader_absence import _line

    ln = _line()
    assert W.decisions_of([(ln["verdict_class"], ln["verdict_label"])]) == {
        "code": 0,
        "two_reader": 1,
        "not_stated": 1,
        "total": 1,
    }
    path = WB.write([ln], tmp_path / "i.xlsx", META, "internal")
    notes = {
        r[0]: r[1]
        for r in openpyxl.load_workbook(path)["Notes"].iter_rows(
            min_row=2, values_only=True
        )
    }
    assert (
        notes["Decisions"] == "Decisions: 1 = code Pass/Fail 0 + two-reader verdicts 1"
    )
    assert notes["Decisions, of which"] == "of which: not stated on the paper 1"
    assert "of which" not in str(
        [
            r[1]
            for r in openpyxl.load_workbook(
                WB.write([], tmp_path / "e.xlsx", META, "internal")
            )["Notes"].iter_rows(min_row=2, values_only=True)
        ]
    )
