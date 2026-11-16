"""Order 14, 16 Nov 2026 night (gates G1, G5, G6; honesty rule 4). Invented data.

1. A "not met" written by the rule check's AI step whose finding names no clause is a question for the engineer, and its AI-written
   rule words are never shown as the book's. Decided on the stored finding, so every viewer sees the same rank (review R-1851).
2. An AI "met" whose field code does not know is a question in every run, worded for the engineer as R94 says;
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
    p = rp.rule_point(row, CTX, _finding(""), VERIFIED, proof=(True, True))
    assert p["rank"] == 3 and p["rule_text"] == "The limit shall be 10 %."


# --- 2 and 3. the AI reviewer


def _ai(verdict: str, **kw) -> dict:
    base = {"item_id": "S-1", "verdict": "Query", "decided_by": "engineer", "ai_verdict": verdict, "why": "x",
            "paper_quote": "Body material: carbon steel", "quotes_checked": {"paper": True, "clause": True, "both": True}}  # fmt: skip
    return {**base, **kw}


def test_a_field_unknown_ai_met_is_a_question_whatever_the_second_reader_says():
    for code in V.FIELD_UNKNOWN_CODES:
        for second in ({"agree": True}, None):
            line = _ai("Pass", reason_code=code, second_opinion=second)
            assert V.met_unsafe_why(line) == V.FIELD_UNKNOWN_MET_WHY
            assert (
                W.final_cap(line, ITEM, None, {"S-1"}, "datasheet")["verdict_label"]
                == W.WORD_QUERY
            )
    assert (
        V.met_unsafe_why(_ai("Pass", reason_code=None, second_opinion={"agree": True}))
        is None
    )  # no objection: unchanged
    held = _ai(
        "Pass", reason_code="pass_field_not_quoted", second_opinion={"agree": True}
    )
    assert (
        V.met_unsafe_why(held) is None
    )  # a KNOWN field the quote missed stays R94's engineer tick (steady in every run)


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
