"""Update 14 (lead-4's row-4 list, u6 vessel #35): a paper that declares one DIVISION of a standard as its design code and cites a clause
of another division of the same standard is a Question decided by code, both quotes lines of the paper. Sections and parts are
complementary, never flagged; a division the paper says is not used is no citation. Behind the update switch. Invented papers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.aim_review import division_cites as DC
from app.aim_review import updates
from app.config import settings


def _paper(*pages: str):
    return SimpleNamespace(pages={i + 1: t for i, t in enumerate(pages)})


DECLARED = "Design code: ZZME Section VIII Div. 1"


def test_a_clause_of_another_division_of_the_declared_standard_is_a_question_with_both_lines():
    paper = _paper(
        DECLARED + "\nDesign pressure 10 barg",
        "Note 4: nozzle loads per ZZME VIII Division 2, clause 4.5.",
    )
    got = DC.lines(paper)
    assert len(got) == 1
    q = got[0]
    assert (q["label"], q["item_id"], q["page"], q["quote"]) == (
        "Question",
        DC.ITEM_ID,
        1,
        DECLARED,
    )
    assert (
        "Division 1 (page 1)" in q["comment"] and "Division 2 on page 2" in q["comment"]
    )
    assert "Note 4: nozzle loads per ZZME VIII Division 2, clause 4.5." in q["comment"]
    assert q["source"] == "not from a held standard" and q["code_compare"] is None


def test_the_same_division_cited_again_is_no_finding():
    assert (
        DC.lines(_paper(DECLARED, "Openings per ZZME Section VIII Div. 1 UG-37.")) == []
    )


def test_other_sections_of_the_same_code_are_complementary_never_flagged():
    paper = _paper(
        DECLARED,
        "Welding per ZZME Section IX Division 1.",
        "Materials per ZZME Section II Div. 2.",
    )
    assert DC.lines(paper) == []


def test_a_division_the_paper_says_is_not_used_is_no_citation():
    assert DC.lines(_paper(DECLARED, "ZZME VIII Div. 2: not applicable.")) == []


def test_roman_division_numbers_read_as_numbers_and_each_other_division_is_asked_once():
    paper = _paper(
        "Construction code: ZZME VIII Div. I",
        "Per ZZME VIII Division II, 5.3.",
        "See also ZZME VIII Div. 2 annex.",
    )
    got = DC.lines(paper)
    assert (
        [g["finding_no"] for g in got] == [1]
        and "Division 1" in got[0]["comment"]
        and "Division 2" in got[0]["comment"]
    )


def test_no_declared_design_code_no_question():
    assert (
        DC.lines(_paper("Per ZZME VIII Div. 2, 4.5.", "Per ZZME VIII Div. 1, UG-27."))
        == []
    )


@pytest.mark.parametrize("on", [False, True])
def test_the_update_switch_decides_whether_the_lines_are_added(monkeypatch, on):
    monkeypatch.setattr(settings, "aim_u13_enabled", on)
    monkeypatch.setattr(settings, "aim_formula_checks_enabled", False)
    state = SimpleNamespace(decided=[])
    updates.formula_lines(
        None, _paper(DECLARED, "Per ZZME VIII Division 2, 4.5."), state
    )
    assert len(state.decided) == (1 if on else 0)


def test_a_form_that_prints_the_label_on_one_line_and_its_value_on_the_next_is_read_as_declared():
    paper = _paper(
        "Design code\nZZME VIII Div. 1\nDesign pressure 10 barg",
        "Note 7: per ZZME VIII Division 2 clause 5.1.",
    )
    got = DC.lines(paper)
    assert len(got) == 1 and got[0]["quote"] == "ZZME VIII Div. 1"


def test_a_label_two_lines_away_is_not_taken_as_the_declared_code():
    paper = _paper(
        "Design code\nService: invented\nZZME VIII Div. 1", "Per ZZME VIII Division 2."
    )
    assert DC.lines(paper) == []
