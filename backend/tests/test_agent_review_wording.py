"""The words of a verdict and the ONE cap at the exit. Invented data only; no model, no network."""

from __future__ import annotations

import pytest

from app import agent_review_verdict as V
from app import agent_review_wording as W

RULE_OK = {"item_id": "R-1", "source": "rule", "rule_label": {"tier": "AI approved"}}
RULE_NO = {
    "item_id": "R-2",
    "source": "rule",
    "rule_tier": V.RULE_NOT_APPROVED,
    "rule_unapproved_why": "values",
}
SKILL = {"item_id": "S-1", "source": "skill"}


def line(verdict, ai=None, **kw):
    return {
        "item_id": "R-1",
        "verdict": verdict,
        "decided_by": "decided by code",
        "ai_verdict": ai,
        **kw,
    }


def test_proven_lines_are_pass_or_fail_and_unproven_ai_verdicts_are_ai_thinks():
    assert W.classify(line("Pass")) == {
        "verdict_label": "Pass",
        "verdict_class": W.CLASS_PROVEN,
        "not_proven_reason": None,
    }
    assert W.classify(line("Fail"))["verdict_label"] == "Fail"
    met = W.classify(line("Query", "Pass", why="no second opinion"))
    assert (
        met["verdict_label"] == "AI thinks: met"
        and met["verdict_class"] == W.CLASS_OPINION
    )
    assert met["not_proven_reason"] == "no second opinion"
    not_met = W.classify(line("Query", "Fail", reason_code="sheet_silent"))
    assert (
        not_met["verdict_label"] == "AI thinks: not met"
        and not_met["not_proven_reason"] == "sheet_silent"
    )
    assert W.classify(line("Query", "Fail"))[
        "not_proven_reason"
    ]  # never an empty reason
    failed = W.classify(line("Query", "Pass", error="timeout"))
    assert (
        failed["verdict_label"] == "Query for the engineer"
        and failed["verdict_class"] == W.CLASS_QUERY
    )
    assert W.classify(line("Query"))["verdict_label"] == "Query for the engineer"
    na = W.classify(line("Query", reason_code="not_applicable"))
    assert na["verdict_class"] == W.CLASS_NOT_APPLICABLE


def test_a_held_code_fail_is_a_query_not_an_ai_thinks_line():
    for flag in ("conditional_hold", "table_note_hold", "context_hold"):
        got = W.classify(line("Query", "Pass", why="held", **{flag: True}))
        assert (
            got["verdict_class"] == W.CLASS_QUERY
            and got["verdict_label"] == "Query for the engineer"
        )


def test_nothing_unproven_is_ever_pass_or_fail():
    for verdict in ("Query",):
        for ai in ("Pass", "Fail", None):
            for extra in (
                {},
                {"error": "x"},
                {"conditional_hold": True},
                {"reason_code": "absent"},
            ):
                label = W.classify(line(verdict, ai, **extra))["verdict_label"]
                assert label not in ("Pass", "Fail")


def test_an_unapproved_rule_line_is_ai_opinion_rule_not_yet_approved():
    got = W.classify(
        line("Pass", "Pass", rule_tier=V.RULE_NOT_APPROVED, rule_unapproved_why="unit")
    )
    assert (
        got["verdict_label"] == "AI thinks: met"
        and got["verdict_class"] == W.CLASS_UNAPPROVED
    )
    assert "unit" in got["not_proven_reason"]
    assert (
        W.classify(line("Fail", "Fail", rule_tier=V.RULE_NOT_APPROVED))["verdict_label"]
        == "AI thinks: not met"
    )
    assert (
        W.classify(line("Fail", None, rule_tier=V.RULE_NOT_APPROVED))["verdict_label"]
        == "Query for the engineer"
    )


def test_apply_marks_a_should_rule_a_recommendation_and_is_idempotent():
    once = W.apply(line("Fail", rule_kind="advice"))
    assert once["recommendation"] is True and W.apply(once) == once
    assert W.apply(line("Fail"))["recommendation"] is False


# ---------------------------------------------------------------- the ONE cap at the exit


@pytest.mark.parametrize("verdict", ["Pass", "Fail"])
def test_final_cap_turns_a_stored_proof_of_a_now_unapproved_rule_into_a_query(verdict):
    """R7 blocking 1: a resumed or stored Pass/Fail line carries no tier; the item's CURRENT tier decides."""
    stored = line(verdict, verdict)  # an earlier run's line: no rule_tier on it
    out = W.final_cap(stored, RULE_NO)
    assert (
        out["verdict"] == "Query"
        and out["unapproved_cap"]
        and out["tier"] == V.TIER_NOT_APPROVED
    )
    assert out["verdict_class"] == W.CLASS_UNAPPROVED and out["verdict_label"] in (
        "AI thinks: met",
        "AI thinks: not met",
    )
    assert out["rule_tier"] == V.RULE_NOT_APPROVED
    assert W.final_cap(out, RULE_NO) == out  # idempotent


def test_final_cap_treats_a_rule_with_no_established_tier_as_not_approved_and_can_rederive_it():
    stored = line("Fail", "Fail")
    bare = {"item_id": "R-1", "source": "rule"}
    assert W.final_cap(stored, bare)["verdict"] == "Query"
    assert W.final_cap(stored, None)["verdict"] == "Query"  # no item at all
    assert (
        W.final_cap(stored, bare, lambda it: "engineer")["verdict"] == "Fail"
    )  # re-derived from the label
    assert W.final_cap(stored, bare, lambda it: "engineer")["tier"] == "engineer"
    assert W.final_cap(stored, bare, lambda it: None)["verdict"] == "Query"


def test_final_cap_keeps_a_proof_of_an_approved_rule_and_of_a_checklist_item():
    got = W.final_cap(line("Fail", "Fail"), RULE_OK)
    assert (
        got["verdict"] == "Fail"
        and got["tier"] == "AI approved"
        and got["verdict_class"] == W.CLASS_PROVEN
    )
    skill = W.final_cap(line("Pass", "Pass", source="skill"), SKILL)
    assert skill["verdict"] == "Pass" and skill["tier"] is None
    stale = W.final_cap(
        line("Query", "Fail", rule_tier=V.RULE_NOT_APPROVED), RULE_OK
    )  # the rule is approved now
    assert (
        "rule_tier" not in stale and stale["verdict"] == "Query"
    )  # a capped Query is never promoted


def test_final_cap_all_finds_each_lines_own_item():
    lines = [
        line("Pass", item_id="R-1"),
        line("Pass", item_id="R-2"),
        line("Pass", item_id="S-1", source="skill"),
        line("Pass", item_id="R-9"),
    ]
    items = {"R-1": RULE_OK, "R-2": RULE_NO, "S-1": SKILL}
    out = {ln["item_id"]: ln["verdict"] for ln in W.final_cap_all(lines, items)}
    assert out == {
        "R-1": "Pass",
        "R-2": "Query",
        "S-1": "Pass",
        "R-9": "Query",
    }  # no item: not established


def test_the_writer_refusal_is_a_hard_rule_on_the_tier():
    assert W.writer_refusal(line("Query")) is None
    assert W.writer_refusal(line("Pass", tier="AI approved")) is None
    assert W.writer_refusal(line("Fail", tier="owner")) is None
    assert W.writer_refusal(line("Fail", tier="engineer")) is None
    assert W.writer_refusal(line("Fail", tier="not AI approved"))
    assert W.writer_refusal(line("Pass"))  # never went through final_cap
    assert W.writer_refusal(line("Pass", tier=None))  # a rule line without a tier
    assert (
        W.writer_refusal(line("Pass", tier=None, source="skill")) is None
    )  # a checklist line has none


def test_counts_keep_the_classes_apart():
    lines = [
        line("Pass"),
        line("Fail"),
        line("Query", "Pass", why="w"),
        line("Query", "Fail", why="w"),
        line("Query", "Fail", rule_tier=V.RULE_NOT_APPROVED),
        line("Query", "Pass", rule_tier=V.RULE_NOT_APPROVED),
        line("Query"),
        line("Query", reason_code="not_applicable"),
        line("Fail", rule_kind="advice"),
    ]
    c = W.counts(lines)
    assert (
        c["proven_pass"] == 1 and c["proven_fail"] == 2
    )  # the advice line is a proven Fail, counted apart below
    assert (c["ai_thinks_met"], c["ai_thinks_not_met"]) == (1, 1)
    assert (
        c["unapproved_ai_thinks_met"],
        c["unapproved_ai_thinks_not_met"],
        c["unapproved_lines"],
    ) == (1, 1, 2)
    assert (
        c["query_for_the_engineer"] == 1
        and c["not_applicable"] == 1
        and c["recommendation_lines"] == 1
    )
