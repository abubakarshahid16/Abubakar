"""Order 14, 16 Nov 2026 night (gates G1, G5, G6; honesty rule 4). Invented data.

1. A "not met" written by the rule check's AI step whose finding names no clause is a question for the engineer, and its AI-written
   rule words are never shown as the book's. Decided on the stored finding, so every viewer sees the same rank (review R-1851).
2. An AI "met" the pass guard objected to (R94's four codes) is a question in every run, worded for the engineer as R94 says;
   a second answer that was cut off keeps its own words.
3. An AI "not met" the second reader disagreed with is a question, as a disagreed "met" already was."""

from __future__ import annotations

from app import agent_review_verdict as V
from app import agent_review_wording as W
from app import review_points as rp

CTX = {"run_id": "r", "paper_document_id": "p", "readable": frozenset({"p", "doc-book"}), "_library": []}  # fmt: skip
ROW = {"row_kind": "ai_engineering_check", "finding_id": "f1", "page_section": "p.3 - Back pressure", "comment": "Value looks low.",
       "standard_reference": "BOOK-9.pdf", "priority": "3"}  # fmt: skip
VERIFIED = {"submittal": {"verified": True}, "standard": {"verified": True}}
UNSEEN = {"submittal": {"verified": True}, "standard": {"verified": False}}
ITEM = {"item_id": "S-1", "source": "skill", "rule_version_id": None}


def _finding(clause: str = "") -> dict:
    return {"standard_document_id": "doc-book", "standard_clause": clause, "requirement_source_text": "The limit shall be 10 %.",
            "requirement": "The limit shall be 10 %.", "contractor_evidence_text": "12 %"}  # fmt: skip


# --- 1. the rule check's AI step


def test_an_ai_check_not_met_with_no_clause_is_a_question_with_no_book_words():
    for sides in (
        VERIFIED,
        UNSEEN,
    ):  # the same for a viewer who may read the book and one who may not
        p = rp.rule_point(dict(ROW), CTX, _finding(""), sides, proof=(True, True))
        assert p["rank"] == 4 and p["tile"] == "questions" and p["firm"] is None
        assert p["rule_text"] is None and p["clause_quote"] is None


def test_an_ai_check_not_met_with_a_clause_keeps_its_rank_for_every_viewer():
    for sides in (VERIFIED, UNSEEN):
        p = rp.rule_point(dict(ROW), CTX, _finding("5.3.4"), sides, proof=(True, True))
        assert p["rank"] == 3 and p["firm"] == "one reader"


def test_a_clause_named_inside_the_reference_still_counts_as_a_clause():
    row = {
        **ROW,
        "standard_reference": "API 520 cl. 5 (p.7)",
    }  # review R-1851: the display field drops a clause it repeats
    p = rp.rule_point(row, CTX, _finding("5"), VERIFIED, proof=(True, True))
    assert p["rank"] == 3


def test_a_clause_review_not_met_is_unchanged():
    row = {
        **ROW,
        "row_kind": "clause_review",
        "standard_reference": "SAES-D-901 cl. 5.3.4 (p.7)",
    }
    from app import agent_review_pass_guards as pass_guards

    class _Book:  # order 14 lane D (G1): the stored words are shown as the book's only where the linked book holds them
        def book(self, _doc):
            return pass_guards.Book({1: "Intro. The limit shall be 10 %. More."})

    p = rp.rule_point(row, {**CTX, "_book_pages": _Book()}, _finding(""), VERIFIED, proof=(True, True))
    assert p["rank"] == 3 and p["rule_text"] == "The limit shall be 10 %."


# --- 2 and 3. the AI reviewer


def _ai(verdict: str, **kw) -> dict:
    base = {"item_id": "S-1", "verdict": "Query", "decided_by": "engineer", "ai_verdict": verdict, "why": "x",
            "paper_quote": "Body material: carbon steel", "quotes_checked": {"paper": True, "clause": True, "both": True}}  # fmt: skip
    return {**base, **kw}


def test_a_guarded_ai_met_is_a_question_whatever_the_second_reader_says():
    for code in V.GUARD_CODES:
        for second in ({"agree": True}, None):
            line = _ai("Pass", reason_code=code, second_opinion=second)
            assert V.met_unsafe_why(line) == V.GUARD_MET_WHY
            assert (
                W.final_cap(line, ITEM, None, {"S-1"}, "datasheet")["verdict_label"]
                == W.WORD_QUERY
            )
    assert (
        V.met_unsafe_why(_ai("Pass", reason_code=None, second_opinion={"agree": True}))
        is None
    )  # no objection: unchanged


def test_a_guarded_ai_met_whose_second_answer_was_cut_off_keeps_the_cut_off_words():
    line = _ai(
        "Pass",
        reason_code="pass_field_unknown",
        second_opinion={"agree": None, "reason": "stop_max_tokens"},
    )
    out = W.final_cap(line, ITEM, None, {"S-1"}, "datasheet")
    assert out["verdict_label"] == W.WORD_QUERY and out["not_proven_reason"].startswith(
        W.CUT_OFF_WHY
    )


def test_the_guarded_question_is_worded_for_the_engineer_as_r94_says():
    from app import crs_ai_words as words
    from app import crs_ai_workbook as WB

    line = {
        **_ai("Pass", reason_code="pass_field_unknown", second_opinion={"agree": True}),
        "field": "Seal",
    }
    line.update(W.final_cap(line, ITEM, None, {"S-1"}, "datasheet"))
    st, order = WB.status_of(line)
    assert st == words.STATUS_QUERY
    assert "Engineer to check the AI reviewer's view:" in WB.layout_comment(
        line, st, order
    )


def test_an_ai_not_met_the_second_reader_disagreed_with_is_a_question():
    out = W.final_cap(
        _ai("Fail", reason_code="not_met", second_opinion={"agree": False}),
        ITEM,
        None,
        {"S-1"},
        "datasheet",
    )
    assert out["verdict_label"] == W.WORD_QUERY and out["not_proven_reason"].startswith(
        V.DISAGREE_WHY
    )
    kept = W.final_cap(
        _ai("Fail", reason_code="not_met", second_opinion={"agree": True}),
        ITEM,
        None,
        {"S-1"},
        "datasheet",
    )
    assert (
        kept["verdict_label"] != W.WORD_QUERY
    )  # the second reader agreed: the AI's "not met" stands as before


# --- second review (R2-1851): the row still says the AI judged it met; a disagreement keeps its action; specific reasons win


def test_a_guarded_question_says_the_ai_judged_it_met_and_the_guards_own_reason():
    item_line = _ai(
        "Pass",
        reason_code="pass_field_not_quoted",
        second_opinion={"agree": True},
        why="the field's words are elsewhere",
    )
    out = W.final_cap(item_line, ITEM, None, {"S-1"}, "datasheet")
    line = {**item_line, **out}
    assert out["not_proven_reason"].startswith(
        f"{V.GUARD_MET_WHY}: the field's words are elsewhere"
    )
    assert V.moved_by_guard(
        line
    )  # the workbook's "One AI reader's view, not confirmed: the requirement is met." follows from this


def test_a_guarded_met_the_second_reader_disagreed_with_keeps_the_disagreement_action():
    from app import crs_comments

    line = _ai(
        "Pass", reason_code="pass_field_unknown", second_opinion={"agree": False}
    )
    assert (
        crs_comments.guarded_question_words(line) == ""
    )  # the readers-disagree action stays, as before
    assert crs_comments.guarded_question_words(
        _ai("Pass", reason_code="pass_field_unknown", second_opinion=None)
    )


# --- round 3 (R3-1851): one home per rule; a cut always carries its mark; each fix reached through its call site


def test_the_one_reader_view_is_cut_with_the_visible_mark():
    short = W.one_reader_view({"comment": "fine"})
    long = W.one_reader_view({"comment": "x " * 500})
    assert short == "fine" and long.endswith("…") and len(long) <= 401


def test_second_said_no_is_one_rule():
    from app import agent_run_second as second

    assert second.disagreed({"agree": False}) is True
    for other in (
        {"agree": True},
        {"agree": None, "reason": "stop_max_tokens"},
        None,
        "no",
    ):
        assert second.disagreed(other) is False


def test_a_cut_off_guarded_met_keeps_its_own_action_not_the_guard_words():
    from app import crs_comments

    cut = _ai(
        "Pass",
        reason_code="pass_field_unknown",
        second_opinion={"agree": None, "reason": "stop_max_tokens"},
    )
    assert crs_comments.guarded_question_words(cut) == ""


def test_the_workbook_action_of_a_disagreed_guarded_met_is_not_the_guard_words():
    from app import crs_ai_workbook as WB

    line = {
        **_ai(
            "Pass", reason_code="pass_field_unknown", second_opinion={"agree": False}
        ),
        "field": "Seal",
    }
    line.update(W.final_cap(line, ITEM, None, {"S-1"}, "datasheet"))
    st, order = WB.status_of(line)
    assert "Engineer to check the AI reviewer's view:" not in WB.layout_comment(
        line, st, order
    )


def test_a_deferring_quote_wins_over_the_generic_disagreement():
    line = _ai("Fail", reason_code="absent", second_opinion={"agree": False}, paper_quote="Set pressure: TBA",
               paper_page=1, quotes_checked={"paper": True, "clause": True, "both": True})  # fmt: skip
    out = W.final_cap(line, ITEM, None, {"S-1"}, "datasheet")
    assert out["verdict_label"] == W.WORD_QUERY and out["not_proven_reason"].startswith(
        V.DEFERRED_WHY
    )
