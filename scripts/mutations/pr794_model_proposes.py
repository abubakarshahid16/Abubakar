"""PR #794 (owner order 2026-10-11, item 4): the model matcher only proposes."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_model_matching.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M794-01", phase=794, description="a model proposal skips the match refusal rules",
             path=_C, anchor='                refused = (match_rules.refusal(requirement, chosen["fact"], sheet=sheet)\n',
             replacement='                refused = (None\n',
             target=_T, keyword="refusal_rule_refuses", tags=("honesty", "critical")),
    Mutation(id="M794-02", phase=794, description="a model-proposed pairing carries the code's status again",
             path=_C, anchor=('                verdict = {**verdict,\n'
                              '                           "status": NEEDS_ENGINEER_REVIEW,\n'
                              '                           "rationale": (\n'
                              '                               f"{MODEL_PAIR_PREFIX}'),
             replacement=('                verdict = {**verdict,\n'
                          '                           "rationale": (\n'
                          '                               f"{MODEL_PAIR_PREFIX}'),
             target=_T, keyword="labelled_medium", tags=("honesty", "critical")),
    Mutation(id="M794-03", phase=794, description="a refused model proposal is not counted by its rule",
             path=_C, anchor='                    rule_refusals[refused] = rule_refusals.get(refused, 0) + 1\n',
             replacement='',
             target=_T, keyword="refusal_rule_refuses", tags=("honesty",)),
)
