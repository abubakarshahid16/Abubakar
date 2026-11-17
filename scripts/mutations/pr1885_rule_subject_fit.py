"""PR #1885 (order 14 LPV V1): a rule is asked only when the thing it is about fits the paper. Entries for the rule check's gate in
`comparison.py` (the danger zone); the rule itself lives in `rule_subject_fit.py`."""
from __future__ import annotations

from ._base import APP, Mutation

_P = APP / "comparison.py"
_T = "tests/test_lpv_rule_subject_fit.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M1885-01", phase=1885, description="the gate's kept list is ignored: a rule about a part the paper lacks is compared",
             path=_P, anchor="    requirements, unfit = rule_subject_fit.gate_for_run(requirements, submittal_id)\n",
             replacement="    unfit = rule_subject_fit.gate_for_run(requirements, submittal_id)[1]\n",
             target=_T, keyword="rule_check_review_does_not_apply_the_unfit_rule", tags=("applicability", "critical")),
    Mutation(id="M1885-02", phase=1885, description="the rule left out gets no does-not-apply decision: dropped silently",
             path=_P, anchor="    extra_not_applied.extend(unfit)\n",
             replacement="    unfit = []\n",
             target=_T, keyword="rule_check_review_does_not_apply_the_unfit_rule", tags=("applicability", "honesty")),
)
