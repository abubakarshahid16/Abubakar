"""Order 228.9b (PR 1329): a side-by-side numbered form is read as two lists and
a lone index number is never an answer."""

from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_228b_side_by_side.py"
_F = APP / "geometry_index_cells.py"

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1329-01",
        phase=1329,
        description="any cell before a label counts as an index, so a real value is dropped",
        path=_F,
        anchor="    if not _ONLY_AN_INTEGER.match(texts[i]):\n        return False\n",
        replacement="    if False:\n        return False\n",
        target=_T,
        keyword="lone_number",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-02",
        phase=1329,
        description="two rows are enough to call a column a running number",
        path=_F,
        anchor="MIN_NUMBERED_ROWS = 3\n",
        replacement="MIN_NUMBERED_ROWS = 2\n",
        target=_T,
        keyword="two_rows_are_not_enough",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-03",
        phase=1329,
        description="a column that does not grow down the table is still a running number",
        path=_F,
        anchor="and numbers == sorted(set(numbers))",
        replacement="and True",
        target=_T,
        keyword="must_grow",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-04",
        phase=1329,
        description="the label/value path no longer splits a side-by-side form",
        path=APP / "geometry_reader.py",
        anchor="_label_value_rows(geometry_index_cells.split(table), alphabet_violations)",
        replacement="_label_value_rows(table, alphabet_violations)",
        target=_T,
        keyword="both_lists",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-05",
        phase=1329,
        description="the answer may be the next item's index number (a wrong value)",
        path=_F,
        anchor="            and not is_index_before_label(texts, i)\n",
        replacement="",
        target=_T,
        keyword="answer_skips_an_index",
        tags=("honesty", "critical"),
    ),
)
