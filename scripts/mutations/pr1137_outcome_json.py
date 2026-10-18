"""PR #1137 (order 117 item 4): a review run's outcome lives in `outcome_json`,
not `refusal_reason`. `comparison.py` is in the danger zone (rule 6)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1137-01",
        phase=1137,
        description="a completed run's outcome is written to the legacy column, so no reader sees its recommendation",
        path=APP / "comparison.py",
        anchor='            "UPDATE review_runs SET status = ?, outcome_json = ?,"\n',
        replacement='            "UPDATE review_runs SET status = ?, refusal_reason = ?,"\n',
        target="tests/test_w3_678_three_way_split.py",
        keyword="a_real_run_counts_unreadable_text_as_applies_but_not_checked",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1137-02",
        phase=1137,
        description="the engineer's decision reads the legacy column, finds no recommendation, and lets an override pass with no reason",
        path=APP / "comparison.py",
        anchor='        stored = json.loads(run.get("outcome_json") or "{}")\n',
        replacement='        stored = json.loads(run.get("refusal_reason") or "{}")\n',
        target="tests/test_review_code.py",
        keyword="overriding_the_recommendation_requires_a_reason",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1137-03",
        phase=1137,
        description="a run's outcome is read from the legacy column, so the screen shows no recommendation",
        path=APP / "comparison.py",
        anchor='        return json.loads(run.get("outcome_json") or "{}")\n',
        replacement='        return json.loads(run.get("refusal_reason") or "{}")\n',
        target="tests/test_review_code.py",
        keyword="the_recommendation_survives_the_decision",
        tags=("honesty", "critical"),
    ),
)
