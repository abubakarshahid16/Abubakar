"""Order 242.4 (PR 1341): a value written "24.8 (109) m3/h (USGPM)" is read as its first system.
Unit reading feeds the unit checks and the comparison, so it is guarded like them (rule 6).
Ids M1341-01 onwards, phase 1341."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_242_dual_unit_form.py"
_TAGS = ("honesty", "o242")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1341-01",
        phase=1341,
        description="a bracketed second system is no longer read, so a printed unit is called missing again",
        path=APP / "datasheets.py",
        anchor="    text = dual_unit_form.first_system(text, same_quantity_twice) or text\n",
        replacement="",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-02",
        phase=1341,
        description="two numbers that are two different quantities are read as one (10 bar and 14 psi)",
        path=APP / "dual_unit_form.py",
        anchor="    if same_quantity(v1, u1, v2, u2):\n",
        replacement="    if True:\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-03",
        phase=1341,
        description="a bracket whose unit is not converted (a gauge mark, a normal mark) is trusted as a second system",
        path=APP / "dual_unit_form.py",
        anchor="    if dim1 is None or dim1 != dim2 or _fold(u1) == _fold(u2):\n        return None\n",
        replacement="    if dim1 is None:\n        return None\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-04",
        phase=1341,
        description="a cell with two different quantities in the trailing form is guessed instead of refused",
        path=APP / "dual_unit_form.py",
        anchor="    return None if interleaved else REFUSED\n",
        replacement="    return None\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-05",
        phase=1341,
        description="a US gallon rate is no longer converted, so its bracket cannot be checked",
        path=APP / "rate_units.py",
        anchor='for _alias, _long in {"usgpm": "usgal/min"}.items():\n',
        replacement="for _alias, _long in {}.items():\n",
        target=_T,
        tags=_TAGS,
    ),
)
