"""PR #910 (#895, PF2): a sentence stating a two-sided limit is stored with
both ends and compared as two ordinary limits. `comparison.py` is in the
danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_895_range_requirements.py"
_C = APP / "comparison.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M910-01", phase=910,
             description="a range is judged against its low end only: a value above the high end meets",
             path=_C,
             anchor='    for operator, bound in ((">=", low), ("<=", high)):\n',
             replacement='    for operator, bound in ((">=", low),):\n',
             target=_T, keyword="above_the_high_end or inside_the_range", tags=("honesty", "critical")),
    Mutation(id="M910-02", phase=910,
             description="a range is judged against its high end only: a value below the low end meets",
             path=_C,
             anchor='    for operator, bound in ((">=", low), ("<=", high)):\n',
             replacement='    for operator, bound in (("<=", high),):\n',
             target=_T, keyword="below_the_low_end", tags=("honesty", "critical")),
    Mutation(id="M910-03", phase=910,
             description="a range meets when only ONE of its ends is met",
             path=_C,
             anchor="    if all(v[\"status\"] == COMPLIANT for _op, _bound, v in ends):\n",
             replacement="    if any(v[\"status\"] == COMPLIANT for _op, _bound, v in ends):\n",
             target=_T, keyword="both_ends_are_decided",
             tags=("honesty", "critical")),
    Mutation(id="M910-04", phase=910,
             description="a range with ends that were not stored is compared as if it had them",
             path=_C,
             anchor="    if shown is None:\n",
             replacement="    if False:\n",
             target=_T, keyword="ends_that_were_not_stored", tags=("honesty",)),
    Mutation(id="M910-05", phase=910,
             description="a range requirement is not paired with any value (left out of the matcher)",
             path=_C,
             anchor=" | {requirements_3b.RANGE_LIMIT}",
             replacement="",
             target=_T, keyword="stored_type_the_api_can_return", tags=("honesty",)),
)
