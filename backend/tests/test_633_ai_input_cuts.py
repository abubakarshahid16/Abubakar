"""#633 item 3: the AI engineering check says what it was NOT shown.

A page longer than the cap and a prompt longer than the whole-prompt cap used to be cut with
nothing recorded, so a sheet the model saw only the start of read as "complete". The run now
carries `input_cut` (page numbers and character counts only), says so in plain words, and the
cloud lane (which is given the whole sheet in one prompt) is not "complete" when part of it was
cut. The local lane, which is asked page by page about blank fields, records the cut and keeps
its own completeness. Invented pages only; the model is a fake.
"""

from __future__ import annotations

import pytest

from app import ai_engineering_check as aic
from app import ai_input_cuts
from tests.test_b3_page_ledger import temp_storage  # noqa: F401 - autouse
from tests.test_review_ai_check import Fake, world  # noqa: F401 - fixture


def test_nothing_cut_is_none_and_says_nothing():
    pages = {1: "a" * 100, 2: "b" * 100}
    assert ai_input_cuts.report(pages, 100) is None
    assert ai_input_cuts.sentence(None) == ""
    assert ai_input_cuts.report({1: "", 2: "  "}, 10) is None


def test_a_long_page_is_counted_by_number_and_characters():
    pages = {1: "a" * 50, 2: "b" * 130, 3: "c" * 100, 4: ""}
    cut = ai_input_cuts.report(pages, 100)
    assert cut == {
        "page_chars": 100,
        "pages_cut": [2],
        "page_lengths": {"2": 130},
        "pages_shown": 3,
        "characters_not_shown": 30,
        "prompt_chars_not_shown": 0,
    }
    text = ai_input_cuts.sentence(cut)
    assert (
        "1 of 3 page(s)" in text
        and "100 characters" in text
        and "30 characters not shown" in text
    )
    assert "not checked by the model" in text


def test_only_the_pages_the_model_was_shown_count():
    pages = {1: "a" * 500, 2: "b" * 500}
    cut = ai_input_cuts.report(pages, 100, shown=[2])
    assert cut["pages_cut"] == [2] and cut["pages_shown"] == 1


def test_a_whole_prompt_cut_is_counted_even_when_no_page_is_long():
    cut = ai_input_cuts.report(
        {1: "a" * 10}, 100, prompt_chars=1000, prompt_length=1250
    )
    assert cut["pages_cut"] == [] and cut["prompt_chars_not_shown"] == 250
    assert "whole prompt was cut (250 characters not shown)" in ai_input_cuts.sentence(
        cut
    )


def test_the_local_lane_counts_only_pages_it_was_asked():
    pages = {1: "a" * 4000, 2: "b" * 4000, 3: "c" * 10}
    local = {"done": [1], "timed_out": [], "failed": [], "not_tried": [2]}
    cut = ai_input_cuts.of_run(local, pages, lambda: "")
    assert cut["pages_cut"] == [1] and cut["page_chars"] == aic.LOCAL_PAGE_CHARS


def test_the_cloud_lane_is_not_complete_when_the_prompt_dropped_part_of_the_sheet(
    request, monkeypatch
):
    _sub, run, scope = request.getfixturevalue("world")
    monkeypatch.setattr(aic, "MAX_PROMPT_CHARS", 50)
    result = aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["input_cut"]["prompt_chars_not_shown"] > 0
    assert status["complete"] is False and result["complete"] is False
    assert (
        "Input cut" in status["plain"] and "not checked by the model" in status["plain"]
    )
    assert "cut before the model saw it" in status["reason"]


def test_a_page_cut_short_is_named_per_page_and_the_review_stays_complete(
    request, monkeypatch
):
    """The planner's call (19:26): one long page is a note on that page, not REVIEW INCOMPLETE."""
    from app import absence

    _sub, run, scope = request.getfixturevalue("world")
    monkeypatch.setattr(aic, "MAX_PAGE_CHARS", 20)
    result = aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["input_cut"]["pages_cut"], "a page longer than 20 characters was cut"
    assert status["complete"] is True and result["complete"] is True
    assert "Input cut" in status["plain"]
    parts = absence.unchecked_parts(
        run_status="completed", outcome={}, ai_status=status
    )
    lines = [p["line"] for p in parts if p["part"] == "ai_check_page_cut"]
    assert lines and all(line.startswith("Page ") for line in lines)
    page_notes = [p for p in parts if p["part"] == "ai_check_page_cut"]
    assert all(p["detail"] for p in page_notes)
    assert not [p for p in parts if p["part"] == "ai_check"], (
        "the AI check is not unchecked"
    )
    assert absence.notice_for(page_notes) == "", (
        "page notes alone never print REVIEW INCOMPLETE"
    )


def test_the_cloud_lane_stays_complete_when_nothing_was_cut(request):
    _sub, run, scope = request.getfixturevalue("world")
    aic.run_check(run, allowed_document_ids=scope, cited=[], provider=Fake())
    status = aic.ai_check_status(run, allowed_document_ids=scope)
    assert status["input_cut"] is None
    assert status["complete"] is True and "Input cut" not in status["plain"]


def test_the_prompt_is_cut_where_it_was_and_the_uncut_text_is_longer(
    request, monkeypatch
):
    sub, run, _scope = request.getfixturevalue("world")
    pages = aic.datasheet_pages(sub)
    held = aic._held_standards(run)
    monkeypatch.setattr(aic, "MAX_PROMPT_CHARS", 300)
    full = aic.build_prompt([], pages, ["API 610"], held, cap=False)
    assert aic.build_prompt([], pages, ["API 610"], held) == full[:300]
    assert len(full) > 300


@pytest.mark.parametrize("pages", [{}, {1: ""}])
def test_no_text_no_report(pages):
    assert ai_input_cuts.report(pages, 10, prompt_chars=10, prompt_length=0) is None


def test_a_12000_character_page_fits_and_a_20000_one_is_noted_on_that_page_only():
    assert aic.MAX_PAGE_CHARS >= 12_000, (
        "the longest page counted on a real sheet is about 11,000"
    )
    pages = {1: "x" * 12_000, 2: "y" * 20_000, 3: "short"}
    cut = ai_input_cuts.report(pages, aic.MAX_PAGE_CHARS)
    assert cut["pages_cut"] == [2]
    [line] = ai_input_cuts.page_lines(cut)
    assert (
        line.startswith("Page 2:")
        and "20,000" in line
        and f"{aic.MAX_PAGE_CHARS:,}" in line
    )
    assert ai_input_cuts.report({1: "x" * 12_000}, aic.MAX_PAGE_CHARS) is None
    assert ai_input_cuts.page_lines(None) == []


def test_the_settle_rule_only_a_prompt_cut_makes_the_cloud_run_incomplete():
    page_only = {"pages_cut": [2], "prompt_chars_not_shown": 0}
    assert ai_input_cuts.settle(page_only, None, True, None) == (True, None)
    prompt_cut = {"pages_cut": [], "prompt_chars_not_shown": 9}
    assert ai_input_cuts.settle(prompt_cut, None, True, None)[0] is False
    assert ai_input_cuts.settle(prompt_cut, {"done": []}, True, None) == (True, None)
