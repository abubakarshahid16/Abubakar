"""PR #794 (owner order 2026-10-11, item 4; planner decision 09:11 UTC): the
model matcher only proposes - its choice is used when, and only when, it
passes the match refusal rules."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_model_matching.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M794-01", phase=794, description="a model proposal skips the match refusal rules",
             path=_C, anchor='                refused = (match_rules.refusal(requirement, chosen["fact"], sheet=sheet)\n',
             replacement='                refused = (None\n',
             target=_T, keyword="refusal_rule_refuses", tags=("honesty", "critical")),
    Mutation(id="M794-02", phase=794, description="an AI-paired finding does not say who paired it",
             path=_C, anchor="                    f\"{MODEL_PAIR_PREFIX}{match.get('reason') or ''}. \"\n",
             replacement="",
             target=_T, keyword="labelled_medium", tags=("honesty",)),
    Mutation(id="M794-03", phase=794, description="a refused model proposal is not counted by its rule",
             path=_C, anchor='                    rule_refusals[refused] = rule_refusals.get(refused, 0) + 1\n',
             replacement='',
             target=_T, keyword="refusal_rule_refuses", tags=("honesty",)),
)
