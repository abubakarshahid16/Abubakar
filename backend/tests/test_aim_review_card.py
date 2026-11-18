"""The comment card's severity and proof (review of the cards branch, 18 Nov 2026): "Must fix" and "compared by code" only for
code's OWN verdict (shown "Fail / Pass, compared by code"), never for an AI opinion that sits beside a comparison. Invented
points; no database."""

from __future__ import annotations

import pytest

from app import aim_review_card as C
from app import aim_review_store as ST
from app.aim_review_gate import AI_MARK

FAIL = {"result": "fail", "why": "25 bar <= 20 bar: false"}


def _p(shown, label, **over):
    return {"n": 1, "label": label, "shown_label": shown, "code_note": "", "deferred": False, "ask": "", "source": "held standard",
            "compare_result": "", "compare_kind": "", "topic": "t", "field": "f", "quote": "q", "comment": "c",
            "standard": "STD-X", "clause": "4.1", "compared": "", "page": 1, **over}  # fmt: skip


@pytest.mark.parametrize(
    "point",
    [
        # (a) a paper-vs-paper pairing the AI chose: code compared two paper quotes, but the line is an AI opinion
        _p("AI opinion", "AI opinion", compare_result="fail", compare_kind="verified paper quotes"),
        # (b) an always-on / knowledge item with numbers: compared, but an AI opinion beside "engineering knowledge"
        _p("AI opinion", "AI opinion", compare_result="fail", compare_kind="verified quotes",
           source="engineering knowledge (book not held)"),
        # an AI "not met" beside a failed comparison is still an AI verdict
        _p("AI opinion: not met", "Not met", compare_result="fail", compare_kind="verified quotes"),
    ],
)  # fmt: skip
def test_an_ai_opinion_beside_a_comparison_is_never_must_fix_nor_compared_by_code(
    point,
):
    assert C.point_severity(point) == C.CHECK
    assert C.proven([point]) == AI_MARK


def test_a_comparison_that_could_not_run_is_never_compared_by_code():
    # (c) result "cannot" with a read_from set: code ran no verdict
    point = _p(
        "Question", "Question", compare_result="cannot", compare_kind="verified quotes"
    )
    assert C.proven([point]) == AI_MARK and C.point_severity(point) == C.CHECK


def test_only_codes_own_fail_is_must_fix_and_only_codes_verdicts_are_compared_by_code():
    fail = _p(
        ST.FAIL_BY_CODE,
        "Not met",
        compare_result="fail",
        compare_kind="verified quotes",
    )
    passed = _p(
        ST.PASS_BY_CODE, "Met", compare_result="pass", compare_kind="verified quotes"
    )
    assert (
        C.point_severity(fail) == C.MUST_FIX and C.proven([fail]) == "compared by code"
    )
    assert (
        C.point_severity(passed) == C.CHECK and C.proven([passed]) == "compared by code"
    )
    provisional = _p(ST.FAIL_BY_CODE, "Not met", code_note="provisional_fails")
    assert (
        C.point_severity(provisional) == C.CHECK
    )  # a provisional figure is never "Must fix"
