"""#746: the review checklist in the datasheet-checks engine. M6401 onward."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_746_relief_valve_checklist.py"
_D = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M6401", phase=6401, description="the equipment type's checklist is never run",
             path=_D, anchor="    checklist = checklist_for(equipment_type, rules)\n    if checklist:\n",
             replacement="    checklist = checklist_for(equipment_type, rules)\n    if False:\n",
             target=_T, keyword="rule_kind", tags=("checklist", "critical")),
    Mutation(id="M6402", phase=6402, description="an item's condition is ignored, so it applies everywhere",
             path=_D, anchor="    stated = None\n    if condition:\n",
             replacement="    stated = None\n    if False:\n",
             target=_T, keyword="condition_decides", tags=("checklist", "critical")),
    Mutation(id="M6403", phase=6403, description="a percent-of rule compares against the whole value",
             path=_D, anchor="            factor = float(rule[\"percent\"]) / 100.0\n",
             replacement="            factor = 1.0\n",
             target=_T, keyword="breach_is_non_compliant", tags=("checklist",)),
    Mutation(id="M6404", phase=6404, description="a unit named by the label is not used",
             path=_D, anchor="        measured = claims.normalise(str(fact.get(\"raw_value\")), unit)\n",
             replacement="        pass\n",
             target=_T, keyword="condition_decides", tags=("checklist",)),
    Mutation(id="M6405", phase=6405, description="gauge and absolute values are compared",
             path=_D, anchor="            or (left[2] and right[2] and left[2] != right[2])):\n",
             replacement="            ):\n",
             target=_T, keyword="two_scales", tags=("checklist", "units")),
    Mutation(id="M6406", phase=6406, description="a 'does not apply' result is written as a finding",
             path=_D, anchor="    for r in (x for x in results if x[\"status\"] not in (COMPLIANT, NOT_APPLICABLE)):\n",
             replacement="    for r in (x for x in results if x[\"status\"] not in (COMPLIANT,)):\n",
             target=_T, keyword="never_written", tags=("checklist", "honesty")),
    Mutation(id="M6407", phase=6407, description="an item without a source clause is run",
             path=_D, anchor="            raise ValueError(f\"checklist item {item.get('id')!r} needs an id, text and a source clause\")\n",
             replacement="            pass\n",
             target=_T, keyword="without_a_clause", tags=("checklist", "honesty")),
    Mutation(id="M6408", phase=6408, description="the local overlay is never read",
             path=_D, anchor="    if not path.is_file():\n        return []\n",
             replacement="    return []\n",
             target=_T, keyword="local_items", tags=("checklist",)),
    Mutation(id="M6409", phase=6409, description="a value nobody knows is owed is reported missing",
             path=_D, anchor="    if fact is None and condition and stated is None:\n",
             replacement="    if False:\n",
             target=_T, keyword="unknown_condition_stops_only", tags=("checklist", "honesty")),
    Mutation(id="M6410", phase=6410, description="an unknown condition stops items that cannot be wrong",
             path=_D, anchor="        if cond_fact is None and item.get(\"when_unknown\") != \"evaluate\":\n",
             replacement="        if cond_fact is None:\n",
             target=_T, keyword="unknown_condition_stops_only", tags=("checklist",)),
)
