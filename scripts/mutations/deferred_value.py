"""#1475 / PR 1490: a value the sheet defers to the contractor is a query (owner decision D2)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1475_planted_defects.py"
_DV = APP / "deferred_value.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1490-01",
        phase=1490,
        description="the standards comparison no longer holds a verdict on a deferred value",
        path=APP / "comparison.py",
        anchor="    if reason is None and not (reason := _deferred_reason(fact)):\n",
        replacement="    if reason is None:\n",
        target=_T,
        keyword="compare_d2_on",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1490-02",
        phase=1490,
        description="the datasheet checks keep a pass or fail on a deferred value",
        path=APP / "datasheet_checks.py",
        anchor="    return hold_results(out, facts, rules, wanted)\n",
        replacement="    return out\n",
        target=_T,
        keyword="d2_a_deferred",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1490-03",
        phase=1490,
        description="a deferred value a check is compared AGAINST (right-hand side, "
        "self-check pair) no longer holds the check",
        path=_DV,
        anchor='        right = right_of.get(r.get("rule_id"))\n',
        replacement="        right = None\n",
        target=_T,
        keyword="d2_a_deferred_right_hand or d2_a_deferred_self_check",
        tags=("honesty",),
    ),
    Mutation(
        id="M1490-04",
        phase=1490,
        description="a deferred value that would also breach is still stated as a Fail",
        path=_DV,
        anchor='_DECIDED = ("COMPLIANT", "NON_COMPLIANT")\n',
        replacement='_DECIDED = ("COMPLIANT",)\n',
        target=_T,
        keyword="would_also_breach or d2_on_a_value_marked",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1490-05",
        phase=1490,
        description="any note beside a value, not only a deferral phrase, holds the value",
        path=_DV,
        anchor="    return note if note and blank_markers.names_a_marker(note) else None\n",
        replacement="    return note or None\n",
        target=_T,
        keyword="plain_note_that_is_not_a_deferral",
        tags=("honesty",),
    ),
)
