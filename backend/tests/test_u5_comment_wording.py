"""U5 (P4, P5, P6): the action sentence follows what the line HOLDS, the comment carries the AI's reasoning (labelled), the priority
comes from the finding. Invented lines only; no model, no network."""

from __future__ import annotations

from app import crs_ai_words as words
from app import crs_ai_workbook as wb


def query(**kw) -> dict:
    base = {
        "item_id": "R-1", "source": "rule", "standard": "STD-1", "clause": "4.1", "verdict": "Query", "verdict_class": "Query for the engineer",
        "paper_page": 2, "quotes_checked": {"paper": False, "clause": True}, "clause_quote": "The relief valve shall be sized for fire.",
        "field": "Set pressure", "reasoning": "The sheet gives 12 bar against 15 bar asked.",
    }
    return {**base, **kw}


def action_of(line: dict) -> str:
    return wb._contractor_to(line, words.STATUS_QUERY, words.ORDER_QUERY)


# ------------------------------------------------------------------------------------------------ P4: the action follows what the line holds


def test_a_value_stated_on_the_paper_is_confirmed_or_justified_never_stated_again():
    line = query(quotes_checked={"paper": True, "clause": True}, paper_quote="Set pressure 12 bar")
    assert wb.action_case(line) == "stated"
    got = action_of(line)
    assert got == "Contractor to confirm or justify Set pressure against STD-1 clause 4.1."
    assert "to state" not in got


def test_a_value_deferred_on_the_sheet_is_provided_and_says_it_is_deferred():
    by_quote = query(quotes_checked={"paper": True, "clause": True}, paper_quote="Set pressure: by vendor")
    by_code = query(reason_code="value_deferred")
    for line in (by_quote, by_code):
        assert wb.action_case(line) == "deferred"
        assert action_of(line) == "Contractor to provide Set pressure; it is deferred on the sheet."


def test_a_blank_field_is_to_be_stated():
    line = query(reason_code="sheet_silent")
    assert wb.action_case(line) == "blank"
    assert action_of(line) == "Contractor to state Set pressure, or the page where it is shown."


def test_when_code_cannot_tell_the_engineer_checks_and_the_contractor_is_not_asked():
    line = query(reason_code="needs_drawing_or_calc")  # no verified quote, not silent, not deferred
    assert wb.action_case(line) == "unknown"
    assert action_of(line) == "Engineer to check Set pressure."


def test_the_case_comes_from_the_verified_quote_not_from_the_readers_words():
    line = query(paper_quote="Set pressure 12 bar", reasoning="The paper states the value clearly.")  # quote NOT verified
    assert wb.action_case(line) != "stated"


def test_a_proven_fail_and_an_opinion_keep_their_own_sentences():
    fail = query(verdict="Fail")
    assert wb._contractor_to(fail, words.STATUS_FAIL, words.ORDER_FAIL).startswith("Contractor to revise Set pressure")
    opinion = wb._contractor_to(query(), words.STATUS_AI, words.ORDER_AI_NOT_MET)
    assert opinion.startswith("Contractor to check Set pressure against")


# ------------------------------------------------------------------------------------------------ P5: the comment carries the AI's reasoning


def test_the_comment_of_a_query_carries_the_ais_reasoning_labelled_as_its_view():
    cell = wb.layout_comment(query(), words.STATUS_QUERY, words.ORDER_QUERY)
    part2 = cell.split("\n")[1]
    assert "The AI reviewer's reasoning (not proven by code): The sheet gives 12 bar against 15 bar asked." in part2
    assert cell.split("\n")[2] == action_of(query())  # part 3 is the P4 sentence


def test_a_proven_fail_carries_no_ai_reasoning_and_a_code_word_never_reaches_it():
    proven = query(verdict="Fail", decided_by="decided by code", compare={"decided": True, "verdict": "does_not_meet"})
    assert "reasoning" not in wb.layout_comment(proven, words.STATUS_FAIL, words.ORDER_FAIL).lower()
    coded = query(reasoning="not_met because pressure_relief S-EQ-04 is missing")
    out = wb.layout_comment(coded, words.STATUS_QUERY, words.ORDER_QUERY)
    assert not words.has_banned(out.split("\n")[1].split("reasoning")[-1])


# ------------------------------------------------------------------------------------------------ P6: priority from the finding


def prio(status, order, **kw) -> str:
    return words.priority_ai(status, query(**kw), order)


def test_a_proven_fail_is_always_high():
    assert prio(words.STATUS_FAIL, words.ORDER_FAIL, source="checklist", clause="") == "High"


def test_mandatory_and_safety_is_high_mandatory_is_medium_else_low():
    safety = "The relief valve shall be sized for fire exposure and back pressure."
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety) == "High"
    assert prio(words.STATUS_AI, words.ORDER_AI_NOT_MET, clause_quote=safety) == "High"
    plain = "The nameplate shall be of stainless steel."
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=plain) == "Medium"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=plain, rule_kind="advice") == "Low"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety, source="checklist") == "Low"


def test_a_line_with_no_clause_has_no_priority_and_the_rule_sheet_says_why():
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause="", clause_quote="", requirement="") == ""
    assert "no clause" in words.PRIORITY_RULE_AI.lower()
    for pass_like in (words.STATUS_PASS, words.STATUS_AI):
        assert words.priority_ai(pass_like, query(), words.ORDER_PASS if pass_like == words.STATUS_PASS else words.ORDER_AI_MET) == ""


def test_the_workbooks_priority_is_the_new_one_and_the_normal_reviewer_is_untouched():
    assert wb._mandatory_rank(query(clause_quote="The valve shall resist fire."), words.STATUS_QUERY, words.ORDER_QUERY) == "High"
    assert words.priority(words.STATUS_QUERY, {}, words.ORDER_QUERY) == words.LOW  # the normal reviewer's own rule, unchanged
