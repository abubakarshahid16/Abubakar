"""A four-column ruled table that is TWO LABEL / VALUE FORMS SIDE BY SIDE (#929, PF2).

`datasheets.pairs_from_table_shape` takes row 0 of every table three or more columns wide as the
header. For "Service | Air receiver | Vacuum service | No" that threw the first row away and named
every other field after it, and for the next rows it made a label the VALUE of another field
("Design pressure - Vacuum service" = "Design temperature"). Here a four-column table is read as two
pairs per row when the shape proves it, and returns None (the old reading, unchanged) otherwise.

THE SHAPE, general (no label, sheet or layout is named):
  * exactly four columns, at least three rows;
  * the first and third cells of the rows below are LABELS (letters, no digit, at most eight
    words, not a unit) and the second or fourth holds an answer, in at least two rows and at least
    60% of them. A table whose third column holds a unit, a number or a code is not this shape;
  * row 0 is a HEADER only when every word in it is a column-name word (`COLUMN_NAME_WORDS`, a closed
    list) AND it repeats ("Parameter | Value | Parameter | Value"): a four-column header that names
    four different columns ("Item | Required | Offered | Remarks") is an ordinary table and is left to
    the old reading. Any other row 0 is an answer when it is pair-shaped, else a title.
A pair with an empty answer is not emitted: an empty cell alone is not a blank (#1324).
"""

from __future__ import annotations

import re
from collections.abc import Callable

#: The words column names are made of. A row 0 made only of these is a header.
COLUMN_NAME_WORDS = frozenset(
    {
        "description",
        "parameter",
        "parameters",
        "item",
        "items",
        "value",
        "values",
        "unit",
        "units",
        "required",
        "offered",
        "specified",
        "remarks",
        "remark",
        "notes",
        "note",
        "data",
        "property",
        "properties",
        "requirement",
        "requirements",
        "characteristic",
        "characteristics",
        "uom",
        "no",
        "ref",
        "of",
        "and",
    }
)

MIN_PAIRED_ROWS = 2
PAIRED_SHARE = 0.6
MAX_LABEL_WORDS = 8


def _fold(cell: str) -> str:
    return " ".join((cell or "").lower().split())


def is_column_names(row: list[str]) -> bool:
    """Is every word of every filled cell a column-name word?"""
    words = [w for cell in row for w in re.findall(r"[^\W\d_]+", cell.lower())]
    return bool(words) and all(w in COLUMN_NAME_WORDS for w in words)


def _label_like(cell: str, is_unit: Callable[[str], bool]) -> bool:
    words = (cell or "").split()
    return (
        bool(words)
        and len(words) <= MAX_LABEL_WORDS
        and bool(re.search(r"[^\W\d_]", cell))
        and not re.search(r"\d", cell)
        and not is_unit(cell)
    )


def _pair_shaped(row: list[str], is_unit: Callable[[str], bool]) -> bool:
    return (
        _label_like(row[0], is_unit)
        and _label_like(row[2], is_unit)
        and bool(row[1] or row[3])
    )


def two_pairs_per_row(shape: list[list[str]]) -> list[tuple[str, str]] | None:
    """The (label, value) pairs of a side-by-side four-column table, or None when the table is
    anything else (the caller then reads it as before)."""
    from .datasheets import (
        is_table_unit as is_unit,
    )  # late: datasheets imports this module
    from .datasheets import split_label_value

    width = max((len(row) for row in shape), default=0)
    if width != 4 or len(shape) < 3:
        return None
    rows = [[(c or "").strip() for c in row] + [""] * (4 - len(row)) for row in shape]
    first = rows[0]
    if is_column_names(first):
        if not (
            _fold(first[0]) == _fold(first[2]) and _fold(first[1]) == _fold(first[3])
        ):
            return None  # a header naming four different columns: an ordinary table
        start = 1
    else:
        start = 0 if _pair_shaped(first, is_unit) else 1  # an answer, else a title
    body = rows[start:]
    paired = [row for row in body if _pair_shaped(row, is_unit)]
    if len(paired) < MIN_PAIRED_ROWS or len(paired) < PAIRED_SHARE * len(body):
        return None
    out: list[tuple[str, str]] = []
    for row in body:
        out.extend((label, value) for label, value in split_label_value(row) if value)
    return out
