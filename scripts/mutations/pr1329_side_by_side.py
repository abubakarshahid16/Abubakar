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
        description="any two numbers in a row prove a running item number, so a value before a unit is cut",
        path=_F,
        anchor="            if any(abs(m - n) == 1 for m in others):\n",
        replacement="            if any(abs(m - n) >= 1 for m in others):\n",
        target=_T,
        keyword="unrelated_numbers or label_value_unit",
        tags=("honesty", "critical"),
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
        anchor="and run == sorted(set(run))",
        replacement="and True",
        target=_T,
        keyword="must_grow or happens_to_grow",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-04",
        phase=1329,
        description="the label/value path no longer splits a side-by-side form",
        path=APP / "geometry_reader.py",
        anchor="_label_value_rows(gic.split(table), alphabet_violations)",
        replacement="_label_value_rows(table, alphabet_violations)",
        target=_T,
        keyword="both_lists",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-05",
        phase=1329,
        description="the row-number gutter no longer proves the column beside it",
        path=_F,
        anchor="            others = [m for other, m in numbers if other != col] + [\n                m for m in gutter if m is not None\n            ]\n",
        replacement="            others = [m for other, m in numbers if other != col]\n",
        target=_T,
        keyword="gutter_proves",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-06",
        phase=1329,
        description="an empty answer cell takes the next item's number as its value again",
        path=_F,
        anchor="            return REFUSED if _is_next_items_number(texts, i) else i\n",
        replacement="            return i\n",
        target=_T,
        keyword="never_reads_the_next_items_number",
        tags=("honesty", "critical"),
    ),
    Mutation(
        id="M1329-07",
        phase=1329,
        description="any text in the numbered column is cut away with the item numbers",
        path=_F,
        anchor='            if c["column"] in columns and _number(c) is not None\n',
        replacement='            if c["column"] in columns and c["text"]\n',
        target=_T,
        keyword="text_in_the_numbered_column",
        tags=("honesty",),
    ),
    Mutation(
        id="M1329-08",
        phase=1329,
        description="a unit or count word after an empty cell and a number counts as a label (a real value is lost)",
        path=_F,
        anchor="    return len(words) >= 2 or text.strip()[:1].isupper()\n",
        replacement="    return True\n",
        target=_T,
        keyword="unit_after_it_is_still_read",
        tags=("honesty",),
    ),
)
