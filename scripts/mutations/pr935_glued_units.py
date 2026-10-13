"""PR #935 (#917, PF3): a glued one-letter unit is a quantity unless context
says designator. `claims.py` unit code is in the danger zone (rule 6)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_917_glued_units.py"
_C = APP / "claims.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M935-01", phase=935,
             description="a list of designators (5A and 5B) is read as amperes and bels again",
             path=_C,
             anchor='        if glued and len(unit) == 1 and unit.isalpha() and _glued_designator_list(sentence, start, m.end("unit")):\n',
             replacement="        if False:\n",
             target=_T, keyword="designator_is_still_not_a_quantity", tags=("honesty", "critical")),
    Mutation(id="M935-02", phase=935,
             description="a sentence opening with a glued designator is read as a quantity",
             path=_C,
             anchor='        if glued and len(unit) == 1 and unit.isalpha() and not sentence[:begin].strip():\n',
             replacement="        if False:\n",
             target=_T, keyword="sentence_opening_with_a_glued_letter", tags=("honesty", "critical")),
    Mutation(id="M935-03", phase=935,
             description="a lowercase glued unit (3m) is dropped as a lone-letter word again",
             path=_C,
             anchor="        if len(unit) == 1 and unit.isalpha() and not unit.isupper() and not glued:\n",
             replacement="        if len(unit) == 1 and unit.isalpha() and not unit.isupper():\n",
             target=_T, keyword="glued_one_letter_unit_is_a_quantity", tags=("honesty", "critical")),
    Mutation(id="M935-04", phase=935,
             description="a designator-lead skip is not counted",
             path=_C,
             anchor="            skipped(SKIP_DESIGNATOR_LEAD)\n",
             replacement="            pass\n",
             target=_T, keyword="designator_is_still_not_a_quantity", tags=("honesty",)),
)
