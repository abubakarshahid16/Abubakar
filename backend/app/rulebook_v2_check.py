"""#805 plan change 6, part A: one rule's requirement against one submitted value. Pure: no database, no model.

THREE OUTCOMES, and only three: meets, does not meet, cannot tell. A value not mentioned is "cannot tell", never
compliant. So is a rule with no single figure (a sentence, a set of alternatives, a rule that defers to another
document): code has nothing to compare, and an engineer reads it.

Numbers through `numparse`, a second unit of one quantity through `claims.compare_across_units`: no second reader.
That code folds case, so it reads mPa as MPa. A spelling whose case IS its SI prefix is compared only with itself.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from . import claims, numparse

MEETS, DOES_NOT_MEET, CANNOT_TELL = "meets", "does_not_meet", "cannot_tell"
OUTCOMES = (MEETS, DOES_NOT_MEET, CANNOT_TELL)
#: The kinds of requirement. Only the first two hold a figure code can compare.
LIMIT, RANGE, ALTERNATIVES, NO_FIGURE, DEFERS_TO = (
    "limit",
    "range",
    "alternatives",
    "no_figure",
    "defers_to",
)
KINDS = (LIMIT, RANGE, ALTERNATIVES, NO_FIGURE, DEFERS_TO)
COMPARATORS = (">=", ">", "<=", "<", "=", "!=")
#: The unit of a figure whose sentence prints none (the proof refuses a unit left out, so this is a count or a ratio).
NO_UNIT = "none"
#: milli written against a capital (mPa, mW), or mega against a small letter (Mm, Mg): case is the meaning. "MPa",
#: "MPA", "kPa" and "mm" are not here: the unit table reads those for what they are.
_CASE_IS_THE_PREFIX = re.compile(r"^(?:m[A-Z]|M[a-z])")
_TEST = {
    ">=": lambda a, b: a >= b,
    ">": lambda a, b: a > b,
    "<=": lambda a, b: a <= b,
    "<": lambda a, b: a < b,
    "=": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass(frozen=True)
class Outcome:
    """`outcome` None means no check happened, because the rule does not bind here: not a fourth outcome."""

    outcome: str | None
    reason: str


def _holds(
    number: float, unit: str, comparator: str, limit: float, limit_unit: str
) -> bool | None:
    """Does the value satisfy this one bound? None when the answer cannot be stood behind."""
    if limit_unit == NO_UNIT or not unit:
        if limit_unit == NO_UNIT and not unit:
            return _TEST[comparator](number, limit)
        return None
    if unit == limit_unit:
        return _TEST[comparator](number, limit)
    if _CASE_IS_THE_PREFIX.match(unit) or _CASE_IS_THE_PREFIX.match(limit_unit):
        return None
    if claims.same_unit(
        claims.normalise(repr(number), unit),
        claims.normalise(repr(limit), limit_unit),
    ):
        return _TEST[comparator](number, limit)
    if comparator == "!=":
        return None
    crossed = claims.compare_across_units(
        claims.normalise(repr(number), unit),
        claims.normalise(repr(limit), limit_unit, comparator),
    )
    return None if crossed is None else crossed.verdict


def check_requirement(
    requirement: Mapping, value: object, unit: str | None = None
) -> Outcome:
    """The outcome of one requirement for one submitted value and unit."""
    kind = requirement["kind"]
    if kind not in (LIMIT, RANGE):
        return Outcome(CANNOT_TELL, kind)
    if value is None or not str(value).strip():
        return Outcome(CANNOT_TELL, "not_mentioned")
    number = numparse.as_limit(str(value))
    if number is None:
        return Outcome(CANNOT_TELL, "value_unclear")
    said = (unit or "").strip()
    limit_unit = requirement["unit"]
    if kind == LIMIT:
        bounds = [(requirement["comparator"], requirement["value"])]
    else:
        bounds = [(">=", requirement["value_low"]), ("<=", requirement["value_high"])]
    answers = [_holds(number, said, c, limit, limit_unit) for c, limit in bounds]
    if False in answers:
        return Outcome(DOES_NOT_MEET, "compared")
    if None in answers:
        return Outcome(CANNOT_TELL, "units_not_comparable")
    return Outcome(MEETS, "compared")
