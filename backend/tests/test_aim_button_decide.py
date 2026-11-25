"""Order 14, piece B: the ONE Review button's resolver with the general review on, and the way back.

With the old engine on (`REVIEW_OLD_ENGINE_ENABLED=true`, the test session's default) `review_engine.decide` answers exactly as
`origin/main` (c71aaae7) did before the general review existed: the digest below was recorded from that commit's resolver over the
fixed sample of `tests/aim_button_combos.py` (8304 combinations). With the general review on, every kind is taken, the rule check
never runs, and a start that would run nothing is refused with a code.
"""

from __future__ import annotations

import hashlib

import pytest

from app import aim_review_gate
from app import review_engine as E
from app.config import settings
from tests.aim_button_combos import answer, combos
from tests.test_b1_review_engine import open_facts

#: Recorded from c71aaae7's `review_engine.decide` (order 14 integrator, 18 Nov 2026).
OLD_ANSWERS = (8304, "fb212e58833d375fce3bd83f19e42dacd7df55962f8f5c418b8344ea6d5a24d9")


@pytest.fixture
def general(monkeypatch):
    monkeypatch.setattr(settings, "review_old_engine_enabled", False)


def test_with_the_old_engine_on_every_answer_is_the_recorded_old_answer():
    assert aim_review_gate.old_engine_on()
    h, n = hashlib.sha256(), 0
    for choice, kw in combos():
        h.update(answer(E, choice, kw).encode())
        n += 1
    assert (n, h.hexdigest()) == OLD_ANSWERS


def test_local_only_runs_the_general_review_on_the_local_model_and_sends_nothing(
    general,
):
    """Planner 25 Nov 2026 22:35: Local only runs the general review on the local model instead of refusing."""
    plan = E.decide("local", open_facts())
    assert plan.refused is None and plan.runs == [E.AI_REVIEW]
    assert plan.part(E.AI_REVIEW).engine == E.ON_LOCAL and not plan.text_leaves
    assert plan.part(E.AI_REVIEW).why == aim_review_gate.LOCAL_RUN_WHY


def test_local_only_with_the_ai_review_switched_off_is_refused_and_runs_nothing(
    general,
):
    plan = E.decide("local", open_facts(agent_enabled=False))
    assert plan.refused_code == E.GENERAL_NOT_ON_LOCAL
    assert plan.refused == aim_review_gate.LOCAL_NOT_AVAILABLE
    assert plan.runs == [] and not plan.text_leaves


@pytest.mark.parametrize(
    "kind",
    [None, "datasheet", "procedure", "contract", "specification", "drawing", "other"],
)
def test_an_explicit_claude_takes_every_kind_and_never_runs_the_rule_check(
    general, kind
):
    plan = E.decide(
        "claude", open_facts(kind=kind, kind_scored=False, scored_allowed=False)
    )
    assert plan.refused is None
    assert plan.part(E.AI_REVIEW).engine == E.ON_CLAUDE
    assert plan.part(E.RULE_CHECK).engine == E.NOT_RUN
    assert plan.part(E.RULE_CHECK).why == aim_review_gate.OLD_ENGINE_OFF_WORDS


def test_automatic_sends_a_scored_kind(general):
    plan = E.decide("automatic", open_facts())
    assert plan.refused is None and plan.runs == [E.AI_REVIEW] and plan.text_leaves


@pytest.mark.parametrize(
    ("facts", "code"),
    [
        ({"is_contract": True, "kind": "contract"}, "NEEDS_YES"),
        ({"kind": None}, "UNSCORED"),
        ({"kind": "drawing", "kind_scored": False}, "UNSCORED"),
        ({"paper_approved": False}, "NOT_APPROVED"),
        ({"books_ok": False}, "BOOKS_NOT_APPROVED"),
    ],
)
def test_automatic_refuses_what_only_an_explicit_claude_may_send_and_says_choose_claude(
    general, facts, code
):
    plan = E.decide("automatic", open_facts(**facts))
    assert plan.refused_code == code and plan.runs == [] and not plan.text_leaves
    assert "choose Claude" in plan.refused
    assert (
        E.decide("claude", open_facts(**facts)).refused is None
    )  # the explicit choice lifts it


@pytest.mark.parametrize(
    ("facts", "code"),
    [
        ({"agent_enabled": False}, "AI_OFF"),
        ({"provider": "ollama"}, "CLAUDE_NOT_SET"),
        ({"provider": "per_task", "agent_engine_claude": False}, "CLAUDE_NOT_SET"),
        ({"lane_open": False}, "LANE_CLOSED"),
        ({"blocked": True}, "BLOCKED"),
        ({"caps_ok": False}, "CAPS"),
    ],
)
def test_what_no_choice_lifts_refuses_automatic_and_claude_alike(general, facts, code):
    for choice in ("automatic", "claude"):
        plan = E.decide(choice, open_facts(**facts))
        assert plan.refused_code == code, choice
        assert plan.runs == [] and not plan.text_leaves
        assert "choose Claude" not in plan.refused


def test_the_kind_blockers_of_the_old_ai_review_do_not_apply(general):
    for kind in (None, "specification", "drawing", "calculation"):
        plan = E.decide("claude", open_facts(kind=kind))
        assert plan.refused_code not in ("KIND_UNKNOWN", "KIND_NOT_OFFERED")
        assert "does not take" not in (plan.part(E.AI_REVIEW).why or "")


def test_a_refused_general_plan_never_has_a_part_on_any_engine(general):
    """A start that would run nothing is never queued: every refusal has no running part (brute force over the sample)."""
    for choice, kw in combos():
        plan = E.decide(choice, E.Facts(**kw))
        if plan.refused:
            assert plan.runs == [] and plan.refused_code
        else:  # Local only runs on the local model (planner 25 Nov 2026 22:35); any other choice on Claude
            assert plan.runs == [E.AI_REVIEW] and plan.part(E.AI_REVIEW).engine == (
                E.ON_LOCAL if choice == E.LOCAL else E.ON_CLAUDE
            )
