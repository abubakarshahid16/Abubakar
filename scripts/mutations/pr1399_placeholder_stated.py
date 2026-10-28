"""PR 1399: a placeholder value is never "stated" in a checklist item. `datasheet_checks.py` is in
the danger zone (rule 6). Ids M1399-01 onwards, phase 1399."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1399-01",
        phase=1399,
        description="a checklist item judges a value blank from the is_blank flag only: '* m3/h' is stated again",
        path=APP / "datasheet_checks.py",
        anchor="if blank_markers.fact_is_placeholder(fact):",
        replacement='if fact.get("is_blank"):',
        target="tests/test_1352_placeholder_not_stated.py",
        keyword="placeholder",
        tags=("honesty",),
    ),
)
