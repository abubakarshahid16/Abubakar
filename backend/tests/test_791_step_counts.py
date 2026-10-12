"""#791 (R25): each AI step carries the numbers its lines print, so the
five-step panel can choose its light from numbers, not from words. A count
the record does not hold is absent, never 0. Invented summaries only."""
from __future__ import annotations

from app import ai_numbers


def test_the_reader_counts_match_its_lines():
    step = ai_numbers.reader({"engine": "ollama", "pages": 5, "pages_read": 1,
                              "code_only": {"2": "timed out", "3": "timed out", "4": "timed out",
                                            "5": "timed out"}, "timed_out": [2, 3, 4, 5],
                              "agreed": 0, "conflicts": 0, "ai_only": 0, "refused_by_gate": 2})
    assert step["counts"] == {"pages": 5, "pages_read": 1, "timed_out": 4, "left_to_code": 4,
                              "agreed": 0, "conflicts": 0, "ai_only": 0, "refused_by_gate": 2}


def test_a_gate_count_the_record_does_not_hold_is_absent_not_zero():
    step = ai_numbers.reader({"engine": "claude", "pages": 1, "pages_read": 1,
                              "agreed": 1, "conflicts": 0, "ai_only": 0})
    assert "refused_by_gate" not in step["counts"]


def test_the_matcher_check_and_wording_carry_their_counts():
    matcher = ai_numbers.matcher({"enabled": True, "engine": "ollama", "sent": 7, "asked": 6,
                                  "proposed": 4, "used": 3, "held": 1, "refused_by_rule": 1,
                                  "declined": 2, "unavailable": 0, "not_asked_budget": 0})
    assert matcher["counts"]["asked"] == 6 and matcher["counts"]["proposed"] == 4
    check = ai_numbers.engineering_check({"ran": True, "complete": True, "proposed_items": 5,
                                          "kept_items": 3, "plain": "x"})
    assert check["counts"] == {"proposed": 5, "kept": 3}
    words = ai_numbers.wording({"enabled": True, "tried": 4, "accepted": 3,
                                "refused": {"number changed": 1}, "not_tried": 2})
    assert words["counts"] == {"tried": 4, "accepted": 3, "refused": 1, "not_tried": 2}


def test_a_step_that_was_off_carries_no_counts():
    assert ai_numbers.reader({"engine": "off", "pages": 3})["counts"] == {}
    assert ai_numbers.matcher({"enabled": False})["counts"] == {}
