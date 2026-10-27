"""A quantity written in two unit systems, the second one in brackets.

API sheets print "24.8 (109) m3/h (USGPM)": the first number and the first unit are one system,
the bracketed number and the bracketed unit the other. The cell reader (`datasheets.measure_value`)
read the number and then met a bracket where it expected the unit, so it kept the value "24.8" with
NO unit, and the mandatory-unit check said "stated ... without a unit" about a sheet that prints
one (the 35B run on the M-03 pump sheet).

The FIRST system is the value. A bracket is read as the other system only when it can be CHECKED:
both units are ones the unit table converts, they are of one dimension, and the two numbers state
one quantity once converted (the rule the slash form "10 barg / 145 psig" uses). Nothing is
accepted unchecked: "10 (20) kW (max)", "10 (12) bar (g)", "5 (7) m3/h (n)" and "10 (20) m3/h
(min)" carry a NOTE in the bracket, not a second system, and are left as they were (no unit
placed). "340 (23.4) psig" (one unit after two numbers) stays unplaced too: which number the unit
belongs to cannot be told.

The trailing form "24.8 m3/h (109 USGPM)" is checked the same way when its two units differ and
both convert: two numbers that do not convert to each other are two quantities, and choosing the
first would be a guess, so the cell is REFUSED (no value), as the slash form already is. No label,
unit or sheet is named here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import claims

#: Returned for a cell that must be refused: a text no value pattern matches, so the cell reader
#: ends with "no value" (what it does for any text that is not a quantity).
REFUSED = "\x00"

_NUM = r"[-+]?\d[\d.,]*"
_UNIT = r"[^\s()\d][^()]*?"
_INTERLEAVED = re.compile(
    rf"^(?P<v1>{_NUM})\s*\(\s*(?P<v2>{_NUM})\s*\)\s*(?P<u1>{_UNIT})\s*\(\s*(?P<u2>{_UNIT})\s*\)\s*$"
)
_TRAILING = re.compile(
    rf"^(?P<v1>{_NUM})\s*(?P<u1>{_UNIT})\s*\(\s*(?P<v2>{_NUM})\s*(?P<u2>{_UNIT})\s*\)\s*$"
)


def _dimension(text: str) -> str | None:
    """The dimension of a unit the table CONVERTS, else None (not a unit, or not converted)."""
    base, _ref = claims.split_reference(text.strip())
    return claims.unit_dimension(base) if base and claims.is_unit(base) else None


def _fold(unit: str) -> str:
    return " ".join(unit.lower().split())


def first_system(
    text: str, same_quantity: Callable[[str, str, str, str], bool]
) -> str | None:
    """ "24.8 m3/h" out of "24.8 (109) m3/h (USGPM)"; `REFUSED` for "24.8 m3/h (30 USGPM)"; None
    when the text is not a checked two-system form (the cell is then read exactly as before)."""
    folded = " ".join(text.split())
    interleaved = _INTERLEAVED.match(folded)
    found = interleaved or _TRAILING.match(folded)
    if found is None:
        return None
    v1, u1, v2, u2 = (found[k] for k in ("v1", "u1", "v2", "u2"))
    dim1, dim2 = _dimension(u1), _dimension(u2)
    if dim1 is None or dim1 != dim2 or _fold(u1) == _fold(u2):
        return None
    if same_quantity(v1, u1, v2, u2):
        return f"{v1} {u1.strip()}"
    return None if interleaved else REFUSED
