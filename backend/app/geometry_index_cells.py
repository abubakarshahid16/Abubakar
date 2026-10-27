"""A bare index number before a label is not an answer (order 228.9b).

A form printed as two label/value lists side by side has, in each row, an item
number in front of every label ("7 | Rated relieving capacity | | 8 | Orifice
designation | "). The headerless label/value path takes the first cell that
starts with a number as the answer, so a row whose first value cell is empty
took the NEXT item's number as its value: "Rated relieving capacity = 8". A cell
that is only a whole number and is followed by a cell of words is that kind of
index, never a measured value. A value is never written as a lone integer
directly before a label; where one is ("Number of stages | 4 | Stage type"),
the answer is the last filled cell as before, so the only cost is a field read
less, never a wrong one. Pure function over the row's cell texts.
"""

from __future__ import annotations

import re
from itertools import pairwise

from . import blank_markers

_ONLY_AN_INTEGER = re.compile(r"^\s*\d{1,3}\s*[.)]?\s*$")
_HAS_WORDS = re.compile(r"[^\W\d_]{2,}")


def is_index_before_label(texts: list[str], i: int) -> bool:
    """True when cell `i` is a lone whole number and the next filled cell is words."""
    if not _ONLY_AN_INTEGER.match(texts[i]):
        return False
    following = next((t for t in texts[i + 1 :] if t), "")
    return bool(_HAS_WORDS.search(following)) and not any(ch.isdigit() for ch in following[:1])


def first_answer(cells: list[dict], texts: list[str], filled: list[int], starts_a_number) -> int | None:
    """The first filled cell after the label that states a value (starts with a
    number, or names a blank marker), skipping an index number before a label."""
    return next(
        (
            i
            for i in filled[1:]
            if cells[i]["text"]
            and (starts_a_number.match(texts[i]) or blank_markers.names_a_marker(texts[i]))
            and not is_index_before_label(texts, i)
        ),
        None,
    )


MIN_NUMBERED_ROWS = 3


def _numbered_columns(table: dict) -> set[int]:
    """Columns that are a running item number: a lone whole number before a
    label in at least MIN_NUMBERED_ROWS rows, growing down the table."""
    seen: dict[int, list[int]] = {}
    for data in table["rows"]:
        cells = sorted(data["cells"], key=lambda c: c["column"])
        texts = [c["text"] or "" for c in cells]
        for i in range(1, len(cells)):
            if texts[i] and is_index_before_label(texts, i) and any(texts[:i]):
                seen.setdefault(cells[i]["column"], []).append(int(re.sub(r"\D", "", texts[i])))
    return {
        col
        for col, numbers in seen.items()
        if len(numbers) >= MIN_NUMBERED_ROWS and numbers == sorted(set(numbers))
    }


def split(table: dict) -> dict:
    """`table` with every row that holds a running item number in the middle cut
    into one row per numbered segment (the item number itself dropped), so a
    form printed as two lists side by side is read as two label/value lists.
    A table with no such column comes back unchanged."""
    columns = _numbered_columns(table)
    if not columns:
        return table
    rows: list[dict] = []
    for data in table["rows"]:
        cells = sorted(data["cells"], key=lambda c: c["column"])
        cuts = [i for i, c in enumerate(cells) if c["column"] in columns and c["text"]]
        if not cuts:
            rows.append(data)
            continue
        bounds = [-1, *cuts, len(cells)]
        for start, stop in pairwise(bounds):
            segment = cells[start + 1 : stop]
            if segment:
                rows.append({**data, "cells": segment})
    return {**table, "rows": rows}
