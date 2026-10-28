"""Order 307, row 76 (PR #1453): a field the sheet gives twice is never called "not given"
(datasheet_checks.py, danger zone). Ids M1453-01.. (CLAUDE.md rule 12)."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1453-01",
        phase=1453,
        description="a field read twice is called not given again",
        path=APP / "datasheet_checks.py",
        anchor="{'is not given' if why == 'absent' else 'has two different values on the sheet'}",
        replacement="{'is not given'}",
        target="tests/test_307_two_values_not_given.py",
        keyword="two_readings_of_one_field_are_not_called_not_given",
        tags=("checklist", "honesty"),
    ),
)
