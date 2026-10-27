"""A form printed as two numbered lists side by side (order 228.9b).

Each row of such a form reads "N | label | value | N+1 | label | value": an item
number in front of every label, the second list continuing the numbering of the
first. The headerless label/value path read only the first pair of a row, and a
row whose first value cell was empty took the NEXT item's number as its value
("Rated relieving capacity = 8").

A column counts as a running item number only on the structure the form really
has: in at least `MIN_NUMBERED_ROWS` rows its whole number is exactly one away
from the whole number in ANOTHER column of the same row (the
row-number gutter included), and its
numbers grow down the table. A `label | value | unit` table has no second
numbered column, so a value such as "8" before a unit is never mistaken for an
index; a table that does not prove the structure comes back unchanged. For such
a form `split` cuts every row at its item-number cells (dropping them), one row
per numbered segment. Pure functions over a table dict; no model, no database.
"""

from __future__ import annotations

import re
from itertools import pairwise

from . import blank_markers, claims

MIN_NUMBERED_ROWS = 3
_WHOLE_NUMBER = re.compile(r"^\s*(\d{1,3})\s*[.)]?\s*$")


def _number(cell: dict) -> int | None:
    found = _WHOLE_NUMBER.match(cell["text"] or "")
    return int(found.group(1)) if found else None


def gutter(texts: list[str], columns: set[int]) -> dict[str, list[str]]:
    """The row's own row-number cells (the gutter columns), as the row's
    "gutter" entry; they are not cells of the row but can prove a numbered column."""
    return {"gutter": [texts[j] for j in sorted(columns)]}


def _numbered_columns(table: dict) -> set[int]:
    """Columns that are a running item number (see the module docstring)."""
    seen: dict[int, list[int]] = {}
    for data in table["rows"]:
        numbers = [(c["column"], _number(c)) for c in data["cells"]]
        numbers = [(col, n) for col, n in numbers if n is not None]
        # The row's own number in the gutter column (dropped from the cells)
        # is the first list's item number: it can prove the column beside it.
        gutter = [_number({"text": t}) for t in data.get("gutter", [])]
        for col, n in numbers:
            others = [m for other, m in numbers if other != col] + [
                m for m in gutter if m is not None
            ]
            if any(abs(m - n) == 1 for m in others):
                seen.setdefault(col, []).append(n)
    return {
        col
        for col, run in seen.items()
        if len(run) >= MIN_NUMBERED_ROWS and run == sorted(set(run))
    }


def split(table: dict) -> dict:
    """`table` with every row cut at its item-number cells into one row per
    numbered segment, so the two lists are read as two label/value lists. A
    table with no proven running-number column comes back unchanged."""
    columns = _numbered_columns(table)
    if not columns:
        return table
    rows: list[dict] = []
    for data in table["rows"]:
        cells = sorted(data["cells"], key=lambda c: c["column"])
        cuts = [
            i
            for i, c in enumerate(cells)
            if c["column"] in columns and _number(c) is not None
        ]
        if not cuts:
            rows.append(data)
            continue
        for start, stop in pairwise([-1, *cuts, len(cells)]):
            segment = cells[start + 1 : stop]
            if segment:
                rows.append({**data, "cells": segment})
    return {**table, "rows": rows}


REFUSED = -1


def _is_a_label(text: str) -> bool:
    """A cell of words that names something: not a unit, and either two or more
    words or one capitalised word ("Orifice designation", "Fluid"); a lone
    lower-case word such as "pcs" is a unit or a count word, not a label."""
    words = re.findall(r"[^\W\d_]{2,}", text)
    if not words or claims.is_unit(text.strip()):
        return False
    return len(words) >= 2 or text.strip()[:1].isupper()


def _is_next_items_number(texts: list[str], i: int) -> bool:
    """Cell `i` is a lone whole number, the cell before it is EMPTY (the answer
    cell of the label to its left) and the next filled cell is a LABEL: the
    number is the next item's index, not that label's value ("Capacity | | 8 |
    Orifice designation"). A unit or count word after it ("Number of stages | |
    4 | pcs") leaves the number as the value."""
    if _number({"text": texts[i]}) is None or i == 0 or texts[i - 1]:
        return False
    following = next((t for t in texts[i + 1 :] if t), "")
    return _is_a_label(following)


def first_answer(
    cells: list[dict], texts: list[str], filled: list[int], starts_a_number
) -> int:
    """The answer cell of a headerless label/value row: the first filled cell
    after the label that starts with a number or names a blank marker, else the
    last filled cell. REFUSED when that first candidate is the next item's
    index number (a blank must never be read as that number): no value."""
    for i in filled[1:]:
        if cells[i]["text"] and (
            starts_a_number.match(texts[i]) or blank_markers.names_a_marker(texts[i])
        ):
            return REFUSED if _is_next_items_number(texts, i) else i
    return filled[-1]
