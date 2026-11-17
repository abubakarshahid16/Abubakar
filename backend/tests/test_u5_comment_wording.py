"""U5 (P4, P5, P6): the action sentence follows what the line HOLDS, the comment carries the AI's reasoning (labelled), the priority
comes from the finding. Invented lines only; no model, no network."""

from __future__ import annotations

from app import crs_ai_actions as actions
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
    assert actions.action_case(line) == "stated"
    got = action_of(line)
    assert got == "Contractor to confirm or justify Set pressure against STD-1 clause 4.1."
    assert "to state" not in got


def test_a_value_deferred_on_the_sheet_is_provided_and_says_it_is_deferred():
    by_quote = query(quotes_checked={"paper": True, "clause": True}, paper_quote="Set pressure: by vendor")
    by_code = query(reason_code="value_deferred")
    for line in (by_quote, by_code):
        assert actions.action_case(line) == "deferred"
    # order 14 lane D: the action says how the sheet marks it and where (a verified quote; else "left open" on its page)
    assert action_of(by_quote) == 'Contractor to provide Set pressure (marked "Set pressure: by vendor" on page 2); it is deferred on the sheet.'
    assert action_of(by_code) == "Contractor to provide Set pressure (left open on page 2); it is deferred on the sheet."


def test_a_blank_field_is_to_be_stated():
    line = query(reason_code="sheet_silent")
    assert actions.action_case(line) == "blank"
    assert action_of(line) == "Contractor to state Set pressure, or the page where it is shown."


def test_when_code_cannot_tell_the_engineer_checks_and_the_contractor_is_not_asked():
    line = query(reason_code="needs_drawing_or_calc")  # no verified quote, not silent, not deferred
    assert actions.action_case(line) == "unknown"
    assert action_of(line) == "Engineer to check Set pressure."


def test_the_case_comes_from_the_verified_quote_not_from_the_readers_words():
    line = query(paper_quote="Set pressure 12 bar", reasoning="The paper states the value clearly.")  # quote NOT verified
    assert actions.action_case(line) != "stated"


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
    assert prio(words.STATUS_FAIL, words.ORDER_FAIL, source="skill", clause="") == "High"


def test_mandatory_and_safety_is_high_mandatory_is_medium_else_low():
    safety = "The relief valve shall be sized for fire exposure and back pressure."
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety) == "High"
    assert prio(words.STATUS_AI, words.ORDER_AI_NOT_MET, clause_quote=safety) == "High"
    plain = "The nameplate shall be of stainless steel."
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=plain) == "Medium"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=plain, rule_kind="advice") == "Low"
    # an item of the engineer's approved checklist is mandatory too: safety + checklist = High, checklist without safety = Medium
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety, source="skill") == "High"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=plain, source="skill") == "Medium"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=plain, source="skill", rule_kind="advice") == "Low"


def test_a_line_with_no_clause_has_no_priority_and_the_rule_sheet_says_why():
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause="", clause_quote="", requirement="") == ""
    assert "no clause" in words.PRIORITY_RULE_AI.lower()
    for pass_like in (words.STATUS_PASS, words.STATUS_AI):
        assert words.priority_ai(pass_like, query(), words.ORDER_PASS if pass_like == words.STATUS_PASS else words.ORDER_AI_MET) == ""


def test_the_workbooks_priority_is_the_new_one_and_the_normal_reviewer_is_untouched():
    assert words.priority_ai(words.STATUS_QUERY, query(clause_quote="The valve shall resist fire."), words.ORDER_QUERY) == "High"
    assert words.priority(words.STATUS_QUERY, {}, words.ORDER_QUERY) == words.LOW  # the normal reviewer's own rule, unchanged


# ------------------------------------------------------------------------------------------------ R68: disagreement, no cut, no contractor comment


def test_when_the_readers_disagree_the_action_says_so_instead_of_confirm_or_justify():
    from app import agent_review_two_reader as two

    line = query(quotes_checked={"paper": True, "clause": True}, paper_quote="Set pressure 12 bar", ai_verdict="Pass",
                 **{two.FIELD: {"verdict": two.V_NOT_MET}})  # fmt: skip
    assert two.disagrees(line)  # code's own flag: the second reader reached the opposite verdict
    assert actions.action_case(line) == "disagree"
    assert action_of(line) == "Engineer to check Set pressure: the readers disagree."
    agreeing = {k: v for k, v in line.items() if k != two.FIELD}
    assert action_of(agreeing).startswith("Contractor to confirm or justify")


def test_the_reasoning_is_never_cut_by_a_character_limit_and_the_contractor_comment_is_never_used():
    long_text = "The AI read the sheet and compared the value. " * 11  # about 506 characters
    assert len(long_text) > 480
    line = query(reasoning=long_text)
    part = actions.reasoning_part(line, words.STATUS_QUERY, "")
    assert " ".join(long_text.split()) in part and not part.endswith("…")
    from app import crs_one

    cells, cut = crs_one.row_of(1, {"id": "x", "ai_reasoning": part.strip(), "tile": "questions", "pill": "Question", "name": "F", "decision": {}})
    assert cells[crs_one.TEAM_COLUMNS.index(crs_one.REASONING_COLUMN)] == part.strip() and cut == 0
    # no `reasoning`: the model's contractor-facing `comment` is not printed under the AI-reasoning label
    assert actions.reasoning_part(query(reasoning="", comment="Contractor to state the value."), words.STATUS_QUERY, "") == ""


# ------------------------------------------------------------------------------------------------ R68b


def test_a_checklist_entry_that_states_its_own_strength_is_believed():
    safety = "The relief valve shall be sized for fire exposure."
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety, source="skill") == "High"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety, source="skill", strength="should") == "Low"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote=safety, source="skill", recommendation=True) == "Low"
    assert prio(words.STATUS_QUERY, words.ORDER_QUERY, clause_quote="The tag shall be steel.", source="skill", strength="advice") == "Low"


def test_a_silent_line_with_a_verified_quote_keeps_its_own_reason_and_action_and_reason_agree():
    """FTU-1 (retracts R68b's "a verified quote means the sheet is not silent"): code found the quote on the page, not that it states the
    value, and not that it does not. A found quote that is more than the field's own label may state it: the reason is neutral and the
    engineer checks; the field's own label alone is where the reader looked, and the contractor states the value."""
    line = query(quotes_checked={"paper": True, "clause": True}, paper_quote="Body: steel", reason_code="sheet_silent",
                 not_proven_reason="the paper is silent on this; a missing statement is not a failure")  # fmt: skip
    assert action_of(line).startswith("Engineer to check Set pressure")
    said = actions.reason_for(line, "the AI reviewer found the paper silent on this")
    assert said == actions.CONTRADICT_REASON
    cell = wb.layout_comment(line, words.STATUS_QUERY, words.ORDER_QUERY)
    assert "a value is stated" not in cell and actions.CONTRADICT_REASON in cell
    from app import crs_one

    point = {"_line": line, "source": "ai_review"}
    assert crs_one.reason_of(point) == actions.CONTRADICT_REASON
    label = {**line, "paper_quote": "Set pressure"}
    assert action_of(label) == "Contractor to state Set pressure, or the page where it is shown."
    assert crs_one.reason_of({"_line": label, "source": "ai_review"}) == actions.NOT_STATED_REASON
    # without a verified quote the stored reason stands
    bare = query(reason_code="sheet_silent")
    assert actions.reason_for(bare, "the paper is silent") == "the paper is silent"
