"""A four-column ruled table that is TWO LABEL / VALUE FORMS SIDE BY SIDE (#929, PF2).

`datasheets.pairs_from_table_shape` takes row 0 of every table three or more columns wide as the
header. For "Service | Air receiver | Vacuum service | No" that threw the first row away and named
every other field after it, and for the next rows it made a label the VALUE of another field
("Design pressure - Vacuum service" = "Design temperature"). Here a four-column table is read as two
pairs per row when the shape proves it, and returns None (the old reading, unchanged) otherwise.

THE SHAPE, general (no label, sheet or layout is named):
  * exactly four columns, at least three rows;
  * in at least 60% of the rows below, the first and third cells are LABELS (letters, no digit, at
    most eight words, not a unit) AND BOTH answers (the second and fourth cells) CARRY A VALUE: a
    digit ("10 barg", "SA-285 Grade C", "0.85"). A table of words only (a matrix of materials, a
    yes/no compliance table) or with words in one answer column is a table of columns, not two
    forms: it is read as before (s3's and cloud-3's probes of the first version);
  * row 0 is a HEADER only when every word in it is a column-name word (`COLUMN_NAME_WORDS`, a closed
    list) AND it repeats ("Parameter | Value | Parameter | Value"): a four-column header that names
    four different columns ("Item | Required | Offered | Remarks") is an ordinary table and is left to
    the old reading. Any other row 0 is an answer when it is label-shaped with something beside the
    labels ("Service | Air receiver | Vacuum service | No"), else a title.
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


def _label_shaped(row: list[str], is_unit: Callable[[str], bool]) -> bool:
    """Labels in the first and third cells and something beside them (a loose test, for row 0)."""
    return (
        _label_like(row[0], is_unit)
        and _label_like(row[2], is_unit)
        and bool(row[1] or row[3])
    )


def _pair_shaped(row: list[str], is_unit: Callable[[str], bool]) -> bool:
    """Labels in the first and third cells AND a value (a digit) in both answers."""
    return (
        _label_like(row[0], is_unit)
        and _label_like(row[2], is_unit)
        and bool(re.search(r"\d", row[1]))
        and bool(re.search(r"\d", row[3]))
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
        start = 0 if _label_shaped(first, is_unit) else 1  # an answer, else a title
    body = rows[start:]
    paired = [row for row in body if _pair_shaped(row, is_unit)]
    if len(paired) < PAIRED_SHARE * len(body):
        return None
    out: list[tuple[str, str]] = []
    for row in body:
        out.extend((label, value) for label, value in split_label_value(row) if value)
    return out
