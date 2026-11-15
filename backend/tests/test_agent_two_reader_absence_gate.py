"""The gates of the absence decision "AI verdict: not stated" (lead, 12 Nov 2026): each condition alone stops the word, and a rule the
code cannot search still earns it, saying so. Invented paper and rule; no network; the code's search is the real `prove_field`."""

# ruff: noqa: F811
from __future__ import annotations

import pytest

import tests.agent_review_support as s
from app import agent_review_absence as A
from app import agent_review_two_reader as two
from app import crs_ai_words as words
from app import db
from app.config import settings
from tests.test_agent_review_guards import run_review, w  # noqa: F401
from tests.test_agent_review_job import lines_of
from tests.test_agent_two_reader import CLASS, stored
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


def test_a_rule_with_no_known_field_never_gets_the_word_nothing_is_asked_and_the_line_stays_an_opinion(
    w, both
):
    """R49 F2: two readers alone are not a decision. The code cannot search: no call, the line stays "AI thinks"."""
    paper()
    fake = _setup_with(w, field_roles=[], page_hint=[1, 2, 3])
    run_id = run_review()
    got = lines_of(run_id)["R-coat"]
    assert (
        got["word"] == "AI thinks: not met"
        and got["verdict_class"] != CLASS
        and fake.absence_bodies == []
    )
    assert (
        absence_step(run_id)["asked"] == 0 and absence_step(run_id)["candidates"] == 0
    )
    assert "two_reader_absence" not in stored(run_id, "R-coat")


def _unreadable(kind):
    """The reviewer's three attack cases (R49 F1), run with and without a field list."""
    if kind == "ocr_failed":
        paper()
        with db.connect() as conn:
            conn.execute(
                "UPDATE page_ledger SET native_status='scanned', ocr_status='failed' WHERE document_id=? AND page_no=2",
                (s.PAPER,),
            )
    elif kind == "tiny":
        paper({**PAGES, 2: "Fig 1"})
    else:  # a page that is not in the stored reading at all
        paper(ledger={1, 3})


@pytest.mark.parametrize("kind", ["ocr_failed", "tiny", "missing_ledger"])
@pytest.mark.parametrize("known_field", [True, False])
def test_an_unreadable_page_vetoes_the_word_on_every_path_and_nothing_is_asked(
    w, both, kind, known_field
):
    _unreadable(kind)
    fake = _setup_with(w, **({} if known_field else {"field_roles": []}))
    run_id = run_review()
    got = lines_of(run_id)["R-coat"]
    assert (
        got["word"] != NOT_STATED
        and got["verdict_class"] != CLASS
        and fake.absence_bodies == []
    )
    st = absence_step(run_id)
    assert st["asked"] == 0 and st["skipped"] == 1


def test_a_value_on_a_page_with_no_field_list_is_not_asked_either(w, both):
    paper({**PAGES, 3: PAGES[3] + "\nDesign pressure: 12 barg"})
    fake = _setup_with(w, field_roles=[])
    run_id = run_review()
    assert (
        lines_of(run_id)["R-coat"]["word"] != NOT_STATED and fake.absence_bodies == []
    )


def test_the_unreadable_page_is_decided_before_the_early_returns_of_the_field_search():
    texts = {1: PAGES[1], 2: "Fig 1", 3: PAGES[3]}
    for carried, item in (
        (None, {"source": "rule"}),  # no field list
        (
            frozenset({ROLE}),
            {"source": "rule", "field_roles": []},
        ),  # a field the code does not know
    ):
        got = A.prove_field(item, "x shall be stated", texts, 3, None, [], carried)
        assert (
            not got.proven and got.code == "absence_page_unreadable" and got.page == 2
        )


def test_the_short_paper_whole_rule_is_off_with_the_switch_off_and_the_requests_are_as_before(
    w, monkeypatch
):
    from app import agent_review_request as rq

    class Pages:
        def count(self, _p):
            return 3

        def page(self, _p, n):
            return f"page {n} text"

    items = [
        {"item_id": "S-1", "page_hint": [2], "question": "q"},
        {"item_id": "R-1", "question": "q"},
    ]
    off = rq.plan_pages(items, Pages(), "p")
    assert (
        off[0]["page_hint"] == [2] and off[0]["page_hint_source"] == "items"
    )  # its own hint stands, as before
    assert (
        off[1]["page_hint"] == [1, 2, 3]
        and off[1]["page_hint_source"] == "short paper: all pages"
    )
    on = rq.plan_pages(items, Pages(), "p", whole_short=True)
    assert (
        on[0]["page_hint"] == [1, 2, 3]
        and on[0]["page_hint_source"] == "short paper: all pages"
    )
    # and the run passes the switch: with both switches off the item keeps its own page hint
    monkeypatch.setattr(settings, "agent_review_two_reader_verdict_enabled", True)
    monkeypatch.setattr(settings, "agent_review_two_reader_absence_enabled", False)
    paper()
    _setup_with(w, page_hint=[2])
    run_id = run_review()
    assert (
        stored(run_id, "R-coat").get("page_hint_source") == "items"
        and lines_of(run_id)["R-coat"]["word"] != NOT_STATED
    )
    monkeypatch.setattr(settings, "agent_review_two_reader_absence_enabled", True)
    monkeypatch.setattr(A, "carried_roles", lambda *_a, **_k: frozenset({ROLE}))
    _setup_with(w, page_hint=[2])
    run_id = run_review()
    assert stored(run_id, "R-coat").get("page_hint_source") == "short paper: all pages"


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


def test_the_sentence_is_built_in_one_home_with_the_absence_words_and_the_searched_code_check():
    sentence = words.absence_verdict_sentence(
        "Design pressure", "The nameplate shall be steel"
    )
    assert sentence.startswith(
        f"{words.ABSENCE_OPENER}: two AI readers each read every page of the paper and found no Design pressure."
    )
    assert (
        words.ABSENCE_OPENER == "Not stated (AI, two readers agree)"
        and "Not met" not in sentence
    )
    assert "quotes verified" not in sentence and sentence.endswith(
        "Engineer to confirm."
    )
    assert words.ABSENCE_CHECK_SEARCHED in sentence


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
