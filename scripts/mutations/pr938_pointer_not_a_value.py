"""PR #938 (#921, PF2): a pointer or placeholder is not a stated value.
`comparison.py` is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_921_a_pointer_is_not_a_value.py"
_C = APP / "comparison.py"
_F = APP / "field_links.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M938-01", phase=938,
             description="a pointer cell is read as a stated value by the comparison",
             path=_C,
             anchor='        stated = stated if field_links.states_a_value(stated) else ""      # #921: a pointer is not a value\n',
             replacement="",
             target=_T, keyword="pointer_does_not_satisfy", tags=("honesty", "critical")),
    Mutation(id="M938-02", phase=938,
             description="a blank marker counts as a stated value",
             path=_F,
             anchor="    if not stated or blank_markers.classify(stated)[0]:\n",
             replacement="    if not stated:\n",
             target=_T, keyword="pointer_does_not_satisfy", tags=("honesty", "critical")),
    Mutation(id="M938-03", phase=938,
             description="a pointer phrase counts as a stated value",
             path=_F,
             anchor="    return _DEFERRAL.match(stated) is None\n",
             replacement="    return True\n",
             target=_T, keyword="pointer_does_not_satisfy", tags=("honesty", "critical")),
)
