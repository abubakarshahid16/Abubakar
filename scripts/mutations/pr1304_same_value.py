"""PR #1304: the same number and unit with a note is ONE value (order 223).
backend/tests/test_223_same_value_with_note.py must notice."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_223_same_value_with_note.py"
_M = APP / "datasheet_checks.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1304-01",
        phase=1304,
        description="the left field of a pair is told apart by its printed text again (a note makes a second value)",
        path=_M,
        anchor="{_key(f) for f in left}",
        replacement="{_shown(f) for f in left}",
        target=_T,
        keyword="same_number_with_a_note",
        tags=("pr1304", "datasheet_checks"),
    ),
    Mutation(
        id="M1304-02",
        phase=1304,
        description="the right field of a pair is told apart by its printed text again",
        path=_M,
        anchor="{_key(f) for f in right}",
        replacement="{_shown(f) for f in right}",
        target=_T,
        keyword="trailing_note",
        tags=("pr1304", "datasheet_checks"),
    ),
    Mutation(
        id="M1304-03",
        phase=1304,
        description="the field a checklist item reads is told apart by its printed text again",
        path=_M,
        anchor="{_key(f) for f in found}",
        replacement="{_shown(f) for f in found}",
        target=_T,
        keyword="checklist_item_reads",
        tags=("pr1304", "datasheet_checks"),
    ),
    Mutation(
        id="M1304-04",
        phase=1304,
        description="a note that changes the meaning (a condition, a bound, a negation) is collapsed into one value",
        path=APP / "same_value.py",
        anchor="    if around is not None and _plain_note(*around):",
        replacement="    if True:",
        target=_T,
        keyword="changes_the_meaning",
        tags=("pr1304", "datasheet_checks"),
    ),
)
