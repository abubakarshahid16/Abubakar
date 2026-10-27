"""A quantity written in two unit systems with the second number in brackets after the first.

API sheets print "24.8 (109) m3/h (USGPM)": the first number and the first unit are one system,
the bracketed number and the bracketed unit the other. The cell reader (`datasheets.measure_value`)
read the number and then met a bracket where it expected the unit, so it kept the value "24.8" with
NO unit, and the mandatory-unit check said "stated ... without a unit" about a sheet that prints
one (the 35B run on the M-03 pump sheet).

The FIRST system is the value, as for "24.8 m3/h (109 USGPM)", which was already read that way.
BOTH brackets must be units the unit table knows, and the first must be one it can convert
("10 (20) kW (max)" is a rate and its qualifier; "10 (20) kW (min)" is not minutes). When both
convert they must be the same dimension and state one quantity (the rule the slash form
"10 barg / 145 psig" uses): two numbers that do not convert to each other are two quantities, and
the cell is left as it was. When the second is recognised but not converted (a US gallon rate),
it cannot be checked, and the first system is still the value. Anything else is not matched: "340 (23.4) psig" (one unit after two numbers) stays unplaced, because which number
the unit belongs to cannot be told. No label, unit or sheet is named here.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from . import claims

_INTERLEAVED = re.compile(
    r"^(?P<v1>[-+]?\d[\d.,]*)\s*\(\s*(?P<v2>[-+]?\d[\d.,]*)\s*\)\s*"
    r"(?P<u1>[^\s()\d][^()]*?)\s*\(\s*(?P<u2>[^\s()\d][^()]*?)\s*\)\s*$"
)


def _dimension(text: str) -> tuple[bool, str | None]:
    """(is a unit the table knows, its dimension or None when it is recognised but not converted)."""
    base, _ref = claims.split_reference(text.strip())
    if not (base and claims.is_unit(base)):
        return False, None
    return True, claims.unit_dimension(base)


def first_system(
    text: str, same_quantity: Callable[[str, str, str, str], bool]
) -> str | None:
    """ "24.8 m3/h" out of "24.8 (109) m3/h (USGPM)", or None when the text is not this form
    or its two halves cannot be shown to state one quantity."""
    found = _INTERLEAVED.match(" ".join(text.split()))
    if found is None:
        return None
    v1, u1, v2, u2 = (found[k] for k in ("v1", "u1", "v2", "u2"))
    (known1, dim1), (known2, dim2) = _dimension(u1), _dimension(u2)
    if not (known1 and known2 and dim1 is not None):
        return None
    if dim2 is None:
        return f"{v1} {u1.strip()}"  # the second unit is recognised, not converted: unchecked
    if dim2 != dim1 or not same_quantity(v1, u1, v2, u2):
        return None
    return f"{v1} {u1.strip()}"
