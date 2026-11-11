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
SKILL = {"item_id": "S-1", "source": "skill", "rule_version_id": None}
SK = {"S-1"}


def line(verdict, ai=None, **kw):
    return {
        "item_id": "R-1",
        "verdict": verdict,
        "decided_by": "decided by code",
        "ai_verdict": ai,
        "paper_quote": "Body material: carbon steel",
        "quotes_checked": {"paper": True, "clause": True},
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
        failed["verdict_label"] == "Not reviewed"
        and failed["verdict_class"] == W.CLASS_NOT_REVIEWED
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
    skill = W.final_cap(line("Pass", "Pass", source="skill"), SKILL, skill_ids=SK)
    assert (
        skill["verdict"] == "Pass"
        and skill["tier"] is None
        and skill["checklist"] is True
    )
    assert W.writer_refusal(skill) is None
    posing = W.final_cap(
        line("Pass", "Pass"),
        {"item_id": "S-1", "source": "skill", "rule_version_id": "r1"},
        skill_ids=SK,
    )
    assert (
        posing["verdict"] == "Query" and posing["tier"] == V.TIER_NOT_APPROVED
    )  # a rule item posing as a checklist item
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
        line("Pass", item_id="S-9", source="skill"),
    ]
    items = {"R-1": RULE_OK, "R-2": RULE_NO, "S-1": SKILL}
    out = {
        ln["item_id"]: ln["verdict"]
        for ln in W.final_cap_all(lines, items, skill_ids=SK)
    }
    # a stored line with NO item is a rule line whose tier is not established, whatever source it claims
    assert out == {
        "R-1": "Pass",
        "R-2": "Query",
        "S-1": "Pass",
        "R-9": "Query",
        "S-9": "Query",
    }


def test_the_writer_refusal_is_a_hard_rule_on_the_tier():
    assert W.writer_refusal(line("Query")) is None
    assert W.writer_refusal(line("Pass", tier="AI approved")) is None
    assert W.writer_refusal(line("Fail", tier="owner")) is None
    assert W.writer_refusal(line("Fail", tier="engineer")) is None
    assert W.writer_refusal(line("Fail", tier="not AI approved"))
    assert W.writer_refusal(line("Pass"))  # never went through final_cap
    assert W.writer_refusal(line("Pass", tier=None))  # a rule line without a tier
    assert W.writer_refusal(
        line("Pass", tier=None, source="skill")
    )  # a raw line claiming to be a checklist line
    assert (
        W.writer_refusal(line("Pass", tier=None, source="skill", checklist=True))
        is None
    )  # set only by final_cap


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


# ---------------------------------------------------------------- "Not reviewed": the AI gave no answer for the item


def test_an_item_the_ai_gave_no_answer_for_is_not_reviewed_never_a_query_about_the_paper():
    for error in ("transport_ReadTimeout", "stop_refusal", "no_answer_for_item"):
        got = W.classify(line("Query", None, error=error))
        assert (
            got["verdict_label"] == "Not reviewed"
            and got["verdict_class"] == W.CLASS_NOT_REVIEWED
        )
        assert error in got["not_proven_reason"]
    cut = W.classify(line("Query", None, error="stop_max_tokens"))
    assert cut["not_proven_reason"] == "no answer from the AI: answer cut off"
    assert W.is_not_reviewed(
        W.apply(line("Query", None, error="x"))
    ) and not W.is_not_reviewed(W.apply(line("Query")))
    counts = W.counts(
        [
            line("Query", error="stop_max_tokens"),
            line("Query", error="other"),
            line("Query"),
        ]
    )
    assert (counts["not_reviewed"], counts["not_reviewed_answer_cut_off"]) == (2, 1)


def test_an_unapproved_rule_whose_answer_was_cut_off_is_not_reviewed():
    got = W.classify(
        line("Query", "Pass", rule_tier=V.RULE_NOT_APPROVED, error="stop_max_tokens")
    )
    assert (
        got["verdict_label"] == "Not reviewed"
        and got["verdict_class"] == W.CLASS_NOT_REVIEWED
    )
    assert got["not_proven_reason"] == "no answer from the AI: answer cut off"


# ---------------------------------------------------------------- owner 16.3: silence is a Query, applied at the one exit


@pytest.mark.parametrize("code", sorted(V.SILENCE_CODES))
@pytest.mark.parametrize(
    "kind", ["procedure", "contract", "drawing", "calculation", "other", None, ""]
)
def test_a_silent_paper_is_a_query_for_every_kind_but_a_datasheet(code, kind):
    for verdict in ("Fail", "Query"):
        out = W.final_cap(
            line(verdict, "Fail", reason_code=code), RULE_OK, paper_kind=kind
        )
        assert (
            out["verdict"] == "Query"
            and out["silence_query"] is True
            and out["why"] == V.SILENCE_WHY
        )
        assert (
            out["verdict_label"] == "Query for the engineer"
            and out["verdict_class"] == W.CLASS_QUERY
        )
        assert out["not_proven_reason"] == V.SILENCE_WHY


def test_a_datasheet_keeps_the_ai_opinion_and_other_reasons_are_never_held_as_silence():
    kept = W.final_cap(
        line("Query", "Fail", reason_code="absent", why="code cannot prove an absence"),
        RULE_OK,
        paper_kind="datasheet",
    )
    assert kept["verdict_label"] == "AI thinks: not met" and "silence_query" not in kept
    other = W.final_cap(
        line("Fail", "Fail", reason_code="not_met"), RULE_OK, paper_kind="procedure"
    )
    assert other["verdict"] == "Fail"
    out = W.final_cap_all(
        [line("Fail", "Fail", reason_code="absent")],
        {"R-1": RULE_OK},
        paper_kind="procedure",
    )
    assert out[0]["verdict"] == "Query"  # the same exit for a whole list
    assert W.counts(out)["silent_paper_queries"] == 1


def test_the_silence_switch_point_is_one_function():
    assert not V.silence_is_query("datasheet") and not V.silence_is_query(" Datasheet ")
    for kind in ("procedure", "contract", "drawing", "test record", "other", None, ""):
        assert V.silence_is_query(kind)
    held = V.hold_silence(
        {"verdict": "Fail", "reason_code": "absent", "decided_by": V.BY_ABSENCE},
        "procedure",
    )
    assert held["verdict"] == V.QUERY and held["silence_query"] is True
    assert (
        V.hold_silence({"verdict": "Fail", "reason_code": "absent"}, "datasheet")[
            "verdict"
        ]
        == V.FAIL
    )
    assert (
        V.hold_silence({"verdict": "Fail", "reason_code": "not_met"}, "procedure")[
            "verdict"
        ]
        == V.FAIL
    )


# ---------------------------------------------------------------- THE EXIT ORDER: every pair of conditions


def case(error=None, silent=False, unapproved=False, verdict="Query", ai="Fail"):
    base = line(verdict, ai, reason_code="absent" if silent else None, error=error)
    item = RULE_NO if unapproved else RULE_OK
    kind = "procedure" if silent else "datasheet"
    return W.final_cap(base, item, paper_kind=kind)


def test_not_reviewed_beats_silence_and_the_cap():
    for silent in (False, True):
        for unapproved in (False, True):
            got = case(error="stop_max_tokens", silent=silent, unapproved=unapproved)
            assert (
                got["verdict_class"] == W.CLASS_NOT_REVIEWED
                and got["verdict_label"] == "Not reviewed"
            ), (silent, unapproved)
            assert W.is_not_reviewed(got)


def test_silence_beats_the_cap_and_says_both_reasons_for_an_unapproved_rule():
    got = case(silent=True, unapproved=True, verdict="Fail")
    assert (
        got["verdict"] == "Query" and got["verdict_label"] == "Query for the engineer"
    )  # never "AI thinks: not met"
    assert got["verdict_class"] == W.CLASS_QUERY
    assert (
        got["not_proven_reason"] == V.SILENCE_WHY + "; the rule is also not AI approved"
    )
    only = case(silent=True, unapproved=False, verdict="Fail")
    assert (
        only["not_proven_reason"] == V.SILENCE_WHY
        and only["verdict_class"] == W.CLASS_QUERY
    )


def test_the_cap_beats_a_proof_and_a_proof_beats_an_opinion_when_nothing_above_applies():
    capped = case(unapproved=True, verdict="Fail")
    assert (
        capped["verdict_class"] == W.CLASS_UNAPPROVED
        and capped["verdict_label"] == "AI thinks: not met"
    )
    proven = case(verdict="Fail")
    assert (
        proven["verdict_label"] == "Fail" and proven["verdict_class"] == W.CLASS_PROVEN
    )
    opinion = case(verdict="Query")
    assert (
        opinion["verdict_class"] == W.CLASS_OPINION
        and opinion["verdict_label"] == "AI thinks: not met"
    )


def test_a_pass_is_never_touched_by_silence():
    got = W.final_cap(
        line("Pass", "Pass", reason_code="absent"), RULE_OK, paper_kind="procedure"
    )
    assert (
        got["verdict"] == "Pass"
        and "silence_query" not in got
        and got["verdict_class"] == W.CLASS_PROVEN
    )
    assert (
        V.hold_silence({"verdict": "Pass", "reason_code": "absent"}, "contract")[
            "verdict"
        ]
        == V.PASS
    )


def test_a_line_with_an_error_is_not_reviewed_even_without_a_stored_class():
    stored = {
        "item_id": "R-1",
        "verdict": "Query",
        "error": "timeout",
    }  # an old line: no verdict_class on it
    assert W.is_not_reviewed(stored)
    assert not W.is_not_reviewed({"item_id": "R-1", "verdict": "Query"})
