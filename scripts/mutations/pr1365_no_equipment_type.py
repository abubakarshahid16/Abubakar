"""#527 (PR 1365): a review with no equipment type selects the standard the procedure names.
Ids M1365-01 onwards, phase 1365."""

from __future__ import annotations

from ._base import APP, Mutation

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1365-01",
        phase=1365,
        description="the library's own document numbers are never looked for in a submittal's text, so a procedure's named standard is not selected",
        path=APP / "applicability.py",
        anchor='    folded_text = " " + _fold_words(text) + " "\n    out: dict[str, dict] = {}\n',
        replacement='    return {}\n    folded_text = " " + _fold_words(text) + " "\n    out: dict[str, dict] = {}\n',
        target="tests/test_527_review_without_equipment_type.py",
        tags=("honesty", "o527"),
    ),
)
