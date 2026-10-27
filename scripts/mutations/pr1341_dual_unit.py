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
        anchor="    if dim2 != dim1 or not same_quantity(v1, u1, v2, u2):\n        return None\n",
        replacement="    if dim2 != dim1:\n        return None\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-03",
        phase=1341,
        description="text that is not a unit is placed as the unit of the first number",
        path=APP / "dual_unit_form.py",
        anchor="    if not (known1 and known2 and dim1 is not None):\n        return None\n",
        replacement="    if False:\n        return None\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-04",
        phase=1341,
        description="a word in the second bracket ('(normal)', '(max)') is read as the other unit system",
        path=APP / "dual_unit_form.py",
        anchor="    if not (known1 and known2 and dim1 is not None):\n        return None\n",
        replacement="    if not (known1 and dim1 is not None):\n        return None\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1341-05",
        phase=1341,
        description="a US gallon rate is no longer a recognised unit, so the bracketed second system is refused",
        path=APP / "claims.py",
        anchor='"l": None, "gpm": None, "usgpm": None, "mpy": None,\n',
        replacement='"l": None, "gpm": None, "mpy": None,\n',
        target=_T,
        tags=_TAGS,
    ),
)
