"""PR #964 (#893): a clause that states one value is a nominal_value; another
value is the engineer's, never a breach. `comparison.py` is in the danger zone
(rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_nominal_values.py"
_C = APP / "comparison.py"
_R = APP / "requirements_3b.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M964-01", phase=964,
             description="a stated value that is not the sheet's value is a breach again",
             path=_C,
             anchor='    if verdict["status"] == NON_COMPLIANT:\n        return {**verdict, "status": NEEDS_ENGINEER_REVIEW, "limit": stated,\n',
             replacement='    if verdict["status"] == NON_COMPLIANT:\n        return {**verdict, "status": NON_COMPLIANT, "limit": stated,\n',
             target=_T, keyword="never_a_breach", tags=("honesty", "critical")),
    Mutation(id="M964-02", phase=964,
             description="a nominal value is not compared at all",
             path=_C,
             anchor="    if requirement.get(\"requirement_type\") == requirements_3b.NOMINAL_VALUE:\n        return _compare_nominal(",
             replacement="    if False:\n        return _compare_nominal(",
             target=_T, keyword="stated_value_within_its_precision", tags=("honesty", "critical")),
    Mutation(id="M964-03", phase=964,
             description="a nominal value is not paired with any value (left out of the matcher)",
             path=_C,
             anchor="| {requirements_3b.RANGE_LIMIT, requirements_3b.NOMINAL_VALUE}",
             replacement="| {requirements_3b.RANGE_LIMIT}",
             target=_T, keyword="stored_matchable_type", tags=("honesty",)),
    Mutation(id="M964-04", phase=964,
             description="the precision is a whole unit wide, not half a unit of the last printed digit",
             path=_R,
             anchor="    return 0.5 * 10 ** -decimals\n",
             replacement="    return 5.0 * 10 ** -decimals\n",
             target=_T, keyword="clause_that_states_one_value or within_its_precision", tags=("honesty", "critical")),
    Mutation(id="M964-05", phase=964,
             description="a limit worded with a comparator (3 m or less) is read as a nominal value",
             path=_R,
             anchor="    if match is None or comparators.directions_in(text) or _NEGATION_WORD.search(text):\n",
             replacement="    if match is None or _NEGATION_WORD.search(text):\n",
             target=_T, keyword="not_a_nominal_value", tags=("honesty", "critical")),
)
