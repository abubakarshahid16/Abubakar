"""R12 (#776): a gas-only item on a liquid service is an engineer's question,
and a value outside its field's plausible range is never stated or computed
from (datasheet_checks + its json, danger zone). Ids M849-01..06 (CLAUDE.md
rule 12)."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_776_phase_implied_and_plausible.py"
_P = APP / "datasheet_checks.py"
_J = APP / "reference" / "datasheet_checks.json"
_TAG = ("checklist", "r12")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(id="M849-01", phase=849, description="an implied other phase is ignored: the item is evaluated as before",
             path=_P, anchor='            if implied and not any(_fold(word) in implied[0] for word in condition["any"]):',
             replacement='            if False:',
             target=_T, keyword="liquid_service_with_no_phase or gas_service_with_no_phase", tags=_TAG),
    Mutation(id="M849-02", phase=849, description="a service naming both phases is read as naming the first",
             path=_P, anchor='    return (phases[0], fact, spec["role"]) if len(phases) == 1 else None',
             replacement='    return (phases[0], fact, spec["role"]) if phases else None',
             target=_T, keyword="naming_both_phases_or_neither", tags=_TAG),
    Mutation(id="M849-03", phase=849, description="service words match inside other words ('boil' as 'oil')",
             path=_P, anchor='              if any(name in words for name in names)]',
             replacement='              if any(name in _fold(_shown(fact)) for name in names)]',
             target=_T, keyword="naming_both_phases_or_neither", tags=_TAG),
    Mutation(id="M849-04", phase=849, description="an implausible value is stated like any other",
             path=_P, anchor='    if (doubt := implausible(fact, field, rules)) is not None:\n        # R12 (#776): an impossible value is never "stated" or compared.',
             replacement='    if False:\n        # R12 (#776): an impossible value is never "stated" or compared.',
             target=_T, keyword="outside_the_plausible_range_is_never_stated", tags=_TAG),
    Mutation(id="M849-05", phase=849, description="the gas area is computed from an implausible k",
             path=_P, anchor='            raise _NotCalculated(doubt)        # R12 (#776): never computed from it',
             replacement='            pass        # R12 (#776): never computed from it',
             target=_T, keyword="area_calculation_refuses_an_implausible_k", tags=_TAG),
    Mutation(id="M849-06", phase=849, description="the k range is widened past any real gas",
             path=_J, anchor='      "plausible": {"max": 1.7}',
             replacement='      "plausible": {"max": 20}',
             target=_T, keyword="outside_the_plausible_range_is_never_stated or plausible_range", tags=_TAG),
)
