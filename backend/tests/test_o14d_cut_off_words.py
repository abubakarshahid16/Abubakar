"""Order 14 lane D (the lead's request): a line whose second AI reader's answer was cut off by its token limit is a Query (lane A,
`two_reader.second_cut_off`), and its reason says so; it never says "two AI readers disagree", because the second reader said
nothing opposite. A real disagreement keeps its own words. Invented lines only."""

from __future__ import annotations

from app import agent_review_verdict as verdict
from app import agent_review_wording as wording

CUT = {"agree": None, "model": "unknown", "reason": "stop_max_tokens"}


def line(second, ai="Pass"):
    return {
        "item_id": "S-INVENTED-2", "ai_verdict": ai, "verdict": "Query", "decided_by": "engineer",
        "reason_code": "pass_field_unknown", "reason_code_ai": "met" if ai == "Pass" else "not_met", "checklist": True,
        "quotes_checked": {"paper": True, "clause": True}, "paper_page": 1,
        "paper_quote": "Coupling guard Required", "clause_quote": "Coupling guards shall be provided.",
        "comment": "The guard is stated as required.", "second_opinion": second,
    }  # fmt: skip


def test_a_cut_off_second_answer_says_it_was_cut_off_not_that_the_readers_disagree():
    for ai in ("Pass", "Fail"):
        got = wording.classify(line(CUT, ai))
        assert got["verdict_class"] == wording.CLASS_QUERY
        assert got["not_proven_reason"] == wording.CUT_OFF_WHY
        assert "disagree" not in got["not_proven_reason"]


def test_a_real_disagreement_keeps_the_disagree_words():
    got = wording.classify(line({"agree": False, "model": "other-model"}))
    assert got["verdict_class"] == wording.CLASS_QUERY
    assert verdict.DISAGREE_WHY in got["not_proven_reason"]
    assert wording.CUT_OFF_WHY not in got["not_proven_reason"]
