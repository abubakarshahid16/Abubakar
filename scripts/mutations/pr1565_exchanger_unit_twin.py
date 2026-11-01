"""PR 1565: the unit check (DS-U1) reads a field as `_one` does, so the unit-less twin of a united
reading is not "needs a unit" (datasheet_checks.py; danger zone). Ids M1565-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_c1_exchanger_scope_box_trace.py"
_TAG = ("checklist", "honesty")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1565-01",
        phase=1565,
        description="the unit check reads every copy again: a united twin 'needs a unit'",
        path=APP / "datasheet_checks.py",
        anchor="            for fact in unit_readings(roles.get(role, [])):",
        replacement="            for fact in roles.get(role, []):",
        target=_T,
        keyword="unit_less_twin_of_a_united_reading_needs_no_unit",
        tags=_TAG,
    ),
)
