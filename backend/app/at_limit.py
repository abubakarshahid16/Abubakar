"""A value AT a worked-out limit is at it in every unit (#1475 finding).

A limit worked out with a factor or a percentage ("1.1 x the MAWP", "10 % above")
can differ from the same number in another unit by float noise, so a value exactly
at the limit read just under it and got a wrong Fail. Two numbers that agree to
1e-9 of their size are the same number: a printed figure never carries nine
digits, so this is never wider than rounding.

Local only: no model, no socket.
"""

from __future__ import annotations

import math

from .config import settings

AT_LIMIT_REL_TOL = 1e-9

_OPS = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
}


def hold(op: str, left: float, right: float) -> bool:
    """`left op right`. Switch on (AT_LIMIT_PRECISION_ENABLED), a value at the
    limit to within float noise counts as equal: it passes `<=` / `>=` and fails
    `<` / `>`. Off: today's plain float comparison."""
    if settings.at_limit_precision_enabled and math.isclose(
        left, right, rel_tol=AT_LIMIT_REL_TOL, abs_tol=0.0
    ):
        return op in (">=", "<=")
    return _OPS[op](left, right)
