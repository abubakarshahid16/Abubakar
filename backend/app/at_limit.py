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



def hold(op: str, left: float, right: float, ops: dict) -> bool:
    """`left op right`, with the caller's operator table `ops` looked up at call
    time (so a slip in that table is still seen). Switch on
    (AT_LIMIT_PRECISION_ENABLED), a value at the limit to within float noise is
    compared as equal to it, through the same operator: it passes `<=` / `>=` and
    fails `<` / `>`. Off: today's plain comparison."""
    if settings.at_limit_precision_enabled and math.isclose(
        left, right, rel_tol=AT_LIMIT_REL_TOL, abs_tol=0.0
    ):
        return ops[op](right, right)
    return ops[op](left, right)
