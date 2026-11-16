"""Order 14 (the lead's decision, 16 Nov 2026), lane A: a second opinion cut off by its token limit counts as a DISAGREEMENT. The
same valve line was "Query" in the two paid runs where the second reader answered "disagree", and "AI thinks: met" in the run where
its answer was cut off. Now it is a Query every time. A second opinion missing for another reason is untouched. Invented line."""

from __future__ import annotations

from app import agent_review_two_reader as two_reader
from app import agent_review_wording as wording

CUT = {"agree": None, "model": "unknown", "reason": "stop_max_tokens"}


def line(second):
    return {
        "item_id": "S-INVENTED-1", "ai_verdict": "Pass", "verdict": "Query", "decided_by": "engineer",
        "reason_code": "pass_field_unknown", "reason_code_ai": "met", "checklist": True,
        "quotes_checked": {"paper": True, "clause": True}, "paper_page": 1,
        "paper_quote": "Lifting lever Required", "clause_quote": "Lifting levers shall be provided on the valves.",
        "comment": "Both accessories are stated as required.", "second_opinion": second,
    }  # fmt: skip


def test_a_cut_off_second_opinion_is_a_disagreement_and_a_query(monkeypatch):
    assert two_reader.second_cut_off(line(CUT)) and two_reader.disagrees(line(CUT))
    got = wording.classify(line(CUT))
    assert (
        got["verdict_class"] == wording.CLASS_QUERY
        and got["verdict_label"] == wording.WORD_QUERY
    )
    # never half of "two readers agree": a line that IS a candidate without the cut (reason "met") is not one with it
    monkeypatch.setattr(
        two_reader, "_pass_guard_ok", lambda _line: True
    )  # the field guard is not what this test is about
    met = {**line(None), "reason_code": "met"}
    assert two_reader.is_candidate(met) and not two_reader.is_candidate(
        {**met, "second_opinion": CUT}
    )


def test_a_disagreement_and_the_cut_off_answer_now_give_the_same_class():
    disagreed = wording.classify(line({"agree": False, "model": "other-model"}))
    assert wording.classify(line(CUT))["verdict_class"] == disagreed["verdict_class"]


def test_a_second_opinion_missing_for_another_reason_is_untouched():
    for second in (
        None,
        {
            "agree": None,
            "model": "unknown",
            "reason": "second reader runs after the first",
        },
    ):
        assert not two_reader.second_cut_off(line(second)) and not two_reader.disagrees(
            line(second)
        )
    assert not two_reader.disagrees(
        {**line(CUT), "ai_verdict": "Query"}
    )  # only an AI met or not met
