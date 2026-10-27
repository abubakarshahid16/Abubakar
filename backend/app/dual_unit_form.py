"""A quantity written in two unit systems, the second one in brackets.

API sheets print "24.8 (109) m3/h (USGPM)": the first number and the first unit are one system,
the bracketed number and the bracketed unit the other. The cell reader (`datasheets.measure_value`)
read the number and then met a bracket where it expected the unit, so it kept the value "24.8" with
NO unit, and the mandatory-unit check said "stated ... without a unit" about a sheet that prints
one (the 35B run on a real pump sheet).

The FIRST system is the value. A bracket is read as the other system only when it can be CHECKED:
both units are ones the unit table converts, they are of one dimension, and the two numbers state
one quantity once converted (the rule the slash form "10 barg / 145 psig" uses). Nothing is
accepted unchecked: "10 (20) kW (max)", "10 (12) bar (g)", "5 (7) m3/h (n)" and "10 (20) m3/h
(min)" carry a NOTE in the bracket, not a second system, and are left as they were (no unit
placed). "340 (23.4) psig" (one unit after two numbers) stays unplaced too: which number the unit
belongs to cannot be told.

The trailing form "24.8 m3/h (109 USGPM)" is read as before (the first number and unit) unless the
bracket is plainly ANOTHER quantity: its two units differ and both convert, and the converted
numbers are more than TRAILING_TOLERANCE apart. Printed conversions are often nominal ("10 bar
(150 psi)", "12 mm (0.5 in)"), so a small gap is a rounding, not a second quantity; a far-off one
("24.8 m3/h (30 USGPM)", "10 bar (14 psi)") is, and choosing the first would be a guess, so the
cell is REFUSED (no value), as the slash form already is. No label,
unit or sheet is named here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import claims

#: Returned for a cell that must be refused: a text no value pattern matches, so the cell reader
#: ends with "no value" (what it does for any text that is not a quantity).
REFUSED = "\x00"

#: How far apart (as a share of the larger) the two numbers of the trailing form may be, converted,
#: before the bracket is another quantity. Nominal figures differ by a few per cent.
TRAILING_TOLERANCE = 0.25

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


def _far_apart(v1: str, u1: str, v2: str, u2: str) -> bool | None:
    """True when `v1 u1` and `v2 u2` convert to numbers more than TRAILING_TOLERANCE apart; None
    when either cannot be converted (nothing can be said)."""
    first, second = claims.normalise(v1, u1), claims.normalise(v2, u2)
    n1, n2 = first.normalized_value, second.normalized_value
    if n1 is None or n2 is None or first.normalized_unit != second.normalized_unit:
        return None
    return abs(n1 - n2) > TRAILING_TOLERANCE * max(abs(n1), abs(n2))


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
    if interleaved:
        return f"{v1} {u1.strip()}" if same_quantity(v1, u1, v2, u2) else None
    return None if _far_apart(v1, u1, v2, u2) is not True else REFUSED
