"""#725 F2: one unit routine reads gauge and absolute pressures. M6201 onward."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_f2_gauge_absolute_units.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M6201", phase=6201, description="a gauge or absolute pressure gets no number again",
             path=APP / "claims.py",
             anchor="        if reference is not None and base:\n            entry = _UNIT_TABLE.get(_fold_unit(base))\n",
             replacement="        if False:\n            entry = _UNIT_TABLE.get(_fold_unit(base))\n",
             target=_T, keyword="has_a_number", tags=("units", "critical")),
    Mutation(id="M6202", phase=6202, description="a gauge pressure is compared with an absolute one",
             path=APP / "claims.py",
             anchor="    if a.reference is not None and b.reference is not None and a.reference != b.reference:\n        return None\n",
             replacement="",
             target=_T, keyword="never_compared", tags=("units", "critical")),
    Mutation(id="M6203", phase=6203, description="the fact's stored normalised value is thrown away",
             path=APP / "comparison.py",
             anchor="    if read.normalized_value is None and stored is not None and stored_unit:\n",
             replacement="    if False:\n",
             target=_T, keyword="stored_normalised", tags=("units",)),
    Mutation(id="M6204", phase=6204, description="gauge against absolute is refused without saying why",
             path=APP / "comparison.py",
             anchor="    if observed.reference and limit.reference and observed.reference != limit.reference:\n",
             replacement="    if False:\n",
             target=_T, keyword="engineer_with_the_reason", tags=("units", "honesty")),
    Mutation(id="M6205", phase=6205, description="a bracketed or compound gauge unit has no dimension",
             path=APP / "claims.py",
             anchor="    if reference is not None and base:\n        return unit_dimension(base)\n",
             replacement="    if False:\n        return unit_dimension(base)\n",
             target=_T, keyword="has_a_number", tags=("units",)),
)
