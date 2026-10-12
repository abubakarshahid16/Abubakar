"""PR #859 (#858, planner decision 12 Oct 2026): a conditional limit nobody
checked, or a pressure of the opposite sign, is never a plain Meets. Two
Meets on a real vessel sheet were ruled false results (gold-lite key)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_858_conditional_and_sign.py"
_C = APP / "comparison.py"
_K = APP / "conditions.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M859-01", phase=859,
             description="a conditional sentence with an empty condition column is compared as a plain limit",
             path=_C,
             anchor="    unread = conditions.unread_condition(requirement) if condition is None else None\n",
             replacement="    unread = None\n",
             target=_T, keyword="engineer_question or states_its_own_condition or never_a_does_not_meet",
             tags=("honesty", "critical")),
    Mutation(id="M859-02", phase=859,
             description="two pressures of opposite sign are compared as the numbers stand",
             path=_C,
             anchor="    opposite = _sign_obstacle(observed, limit)\n",
             replacement="    opposite = None\n",
             target=_T, keyword="by_its_sign or other_way_round", tags=("honesty", "critical")),
    Mutation(id="M859-03", phase=859,
             description="the sign rule also stops a negative temperature (a real, comparable value)",
             path=_C,
             anchor='    if observed.dimension != "pressure" or limit.dimension != "pressure":\n        return None\n',
             replacement="",
             target=_T, keyword="negative_temperature", tags=("honesty",)),
    Mutation(id="M859-04", phase=859,
             description="several limits, each for a different case, are not read as a condition",
             path=_K,
             anchor="    if len(_LIMIT_FOR_A_CASE.findall(text)) >= 2:\n",
             replacement="    if False:\n",
             target=_T, keyword="states_its_own_condition", tags=("honesty", "critical")),
    Mutation(id="M859-05", phase=859,
             description="an opener that only orders the text ('In addition,') is read as a condition",
             path=_K,
             anchor='    r"^\\W*(?:\\(?[0-9a-z]{1,3}\\)\\s*)?(?P<clause>(?:in(?!\\s+" + _NOT_A_CONDITION + r")|where|when|if|unless"\n',
             replacement='    r"^\\W*(?:\\(?[0-9a-z]{1,3}\\)\\s*)?(?P<clause>(?:in|where|when|if|unless"\n',
             target=_T, keyword="only_orders_the_text", tags=("honesty",)),
)
