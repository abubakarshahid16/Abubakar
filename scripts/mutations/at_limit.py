"""#1475 finding: a value at a worked-out limit is at it in every unit."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_1475_at_limit_precision.py"
_M = APP / "datasheet_checks.py"
_A = APP / "at_limit.py"
_TAGS = ("honesty", "critical")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1511-01",
        phase=1511,
        description="above-by limit compared with plain floats again",
        path=_M,
        anchor='        ok = _hold(">=", left[0], right[0] + margin, _OPS)\n',
        replacement="        ok = left[0] >= right[0] + margin\n",
        target=_T,
        keyword="switch_on_a_value_at_the_limit",
        tags=_TAGS,
    ),
    Mutation(
        id="M1511-02",
        phase=1511,
        description="percent-of limit compared with plain floats again",
        path=_M,
        anchor='    ok = _hold(rule["op"], left[0], right[0] * factor, _OPS)\n',
        replacement='    ok = _OPS[rule["op"]](left[0], right[0] * factor)\n',
        target=_T,
        keyword="switch_on_a_value_at_the_limit",
        tags=_TAGS,
    ),
    Mutation(
        id="M1511-03",
        phase=1511,
        description="the at-limit tolerance is widened beyond rounding",
        path=_A,
        anchor="AT_LIMIT_REL_TOL = 1e-9\n",
        replacement="AT_LIMIT_REL_TOL = 1e-2\n",
        target=_T,
        keyword="never_widens",
        tags=_TAGS,
    ),
    Mutation(
        id="M1511-04",
        phase=1511,
        description="a value at a strict limit (> or <) passes",
        path=_A,
        anchor="        return ops[op](right, right)\n",
        replacement="        return True\n",
        target=_T,
        keyword="follows_the_operator",
        tags=_TAGS,
    ),
    Mutation(
        id="M1511-05",
        phase=1511,
        description="the at-limit switch is ignored (always on)",
        path=_A,
        anchor="    if settings.at_limit_precision_enabled and math.isclose(",
        replacement="    if math.isclose(",
        target=_T,
        keyword="today_a_value_at_the_limit",
        tags=_TAGS,
    ),
    Mutation(
        id="M1511-06",
        phase=1511,
        description="the pair consistency rules compare plain floats again",
        path=_M,
        anchor='            ok = _hold(rule["op"], a[0], b[0], _OPS)\n',
        replacement='            ok = _OPS[rule["op"]](a[0], b[0])\n',
        target=_T,
        keyword="pair_consistency",
        tags=_TAGS,
    ),
)
