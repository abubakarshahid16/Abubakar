"""PR #1808 (ONE-REVIEWER.md, owner decision 12 Nov 2026): the calculator STEP of the AI review job. Each entry deletes one control that keeps the step
from running with its setting off, from storing lines before the first reader call, from pairing a fact with a rule of another quantity, or from
re-capping its stored lines on a resume; `tests/test_b1_calculator_step.py` must notice. Ids M1808-01 onwards (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_b1_calculator_step.py"
_K = APP / "agent_review_calculator_run.py"
_TAGS = ("honesty", "critical", "calculator")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1808-01",
        phase=1808,
        description="the setting is not asked: the step runs with AI_REVIEW_CALCULATOR_ENABLED off",
        path=_K,
        anchor="    if not enabled():\n",
        replacement="    if False:\n",
        target=_T,
        keyword="off_the_step_does_nothing",
        tags=_TAGS,
    ),
    Mutation(
        id="M1808-02",
        phase=1808,
        description="the lines are not stored: a run that stops early, or a closed lane, keeps no code line",
        path=_K,
        anchor="        store(line, None)\n",
        replacement="        pass\n",
        target=_T,
        keyword="stored_before_the_first_reader or closed_lane",
        tags=_TAGS,
    ),
    Mutation(
        id="M1808-03",
        phase=1808,
        description="the quantity words are not compared: a fact of another quantity is paired with the rule",
        path=_K,
        anchor="            != wanted\n",
        replacement="            == None\n",
        target=_T,
        keyword="another_quantity",
        tags=_TAGS,
    ),
    Mutation(
        id="M1808-04",
        phase=1808,
        description="the runner takes the code lines back on a resume: they are capped to Query again",
        path=_K,
        anchor='str(v.get("source") or "").strip().casefold() != calc.SOURCE',
        replacement="True",
        target=_T,
        keyword="resumed_run",
        tags=_TAGS,
    ),
    Mutation(
        id="M1808-05",
        phase=1808,
        description="the trace route does not take a slash in the line id: a code line of a tag like A/B answers 404",
        path=APP / "api" / "agent_review.py",
        anchor='"/api/reviews/runs/{review_run_id}/agent/lines/{item_id:path}/trace",\n',
        replacement='"/api/reviews/runs/{review_run_id}/agent/lines/{item_id}/trace",\n',
        target="tests/test_b1_code_trace.py",
        keyword="slash_in_the_id",
        tags=_TAGS,
    ),
    Mutation(
        id="M1808-06",
        phase=1808,
        description="a numeric rule is paired by its item's field roles only, not by its label's own field: nothing pairs on rules whose roles are empty",
        path=_K,
        anchor="    names = guards.field_names(item)\n",
        replacement='    names = [str(r) for r in item.get("field_roles") or []]\n',
        target=_T,
        keyword="label_field",
        tags=_TAGS,
    ),
)
