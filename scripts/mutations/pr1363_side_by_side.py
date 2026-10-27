"""#929 (PR 1363): a four-column table of two forms side by side is read as two pairs per row.
A reading rule, guarded like the unit and comparison code. Ids M1363-01 onwards, phase 1363."""

from __future__ import annotations

from ._base import APP, Mutation

_F = APP / "table_pairs.py"
_T = "tests/test_929_side_by_side_forms.py"
_TAGS = ("honesty", "o929")

MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="M1363-01",
        phase=1363,
        description="a four-column header naming four different columns is read as two forms side by side",
        path=_F,
        anchor="        if not (\n            _fold(first[0]) == _fold(first[2]) and _fold(first[1]) == _fold(first[3])\n        ):\n",
        replacement="        if False:\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1363-02",
        phase=1363,
        description="a cell holding a code or a number counts as a label, so a requirement table is split in two",
        path=_F,
        anchor='        and not re.search(r"\\d", cell)\n',
        replacement="",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1363-03",
        phase=1363,
        description="a pair with an empty answer is emitted, so an empty cell reads as a value",
        path=_F,
        anchor="        out.extend((label, value) for label, value in split_label_value(row) if value)\n",
        replacement="        out.extend((label, value) for label, value in split_label_value(row))\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1363-04",
        phase=1363,
        description="the share of pair-shaped rows is no longer required",
        path=_F,
        anchor="    if len(paired) < PAIRED_SHARE * len(body):\n",
        replacement="    if not paired:\n",
        target=_T,
        tags=_TAGS,
    ),
    Mutation(
        id="M1363-05",
        phase=1363,
        description="a value in only ONE answer column is enough to read a table of words as two forms",
        path=_F,
        anchor='        and bool(re.search(r"\\d", row[1]))\n        and bool(re.search(r"\\d", row[3]))\n',
        replacement='        and bool(re.search(r"\\d", row[1]) or re.search(r"\\d", row[3]))\n',
        target=_T,
        tags=_TAGS,
    ),
)
