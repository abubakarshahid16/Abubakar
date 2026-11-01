"""A BLANK FORM: cover lines that are labels with no value in them.

Owner order 1 Nov: a blank form (labels, no values) is never given a kind from
one of its LABELS ("SERVICE / P&ID NUMBER" is a field, not a drawing title).
General, not per layout: it only counts, on the cover and title pages, the
lines that are a label with nothing after it (a table row whose other cells are
empty or a "By Vendor"/"TBA" placeholder, or "Label:" with nothing after the
colon) against the lines that carry a value. Pure; no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .blank_markers import is_marker

#: Fewer label-only lines than this is not a form, whatever the rest says.
MIN_LABEL_LINES = 5
#: A form is blank when value lines are at most this share of label lines.
_VALUE_SHARE = 0.34
_DIGIT = re.compile(r"\d")


def _cells(line: str) -> list[str]:
    if "|" in line:
        return [c.strip() for c in line.split("|") if c.strip()]
    head, sep, tail = line.partition(":")
    return [head.strip(), tail.strip()] if sep else []


def _is_value(cell: str) -> bool:
    """A cell that says something: not empty, not a placeholder, and either a
    figure or not written in capitals only (capitals are how a form prints its
    own labels)."""
    if len(cell) < 2 or is_marker(cell):  # one character is a tick, not a value
        return False
    return bool(_DIGIT.search(cell)) or cell != cell.upper()


def line_shape(line: str) -> str:
    """`label` (label, nothing after it), `value` (a value follows the label)
    or `other` (a heading or a sentence: no cells)."""
    cells = _cells(line)
    if not cells or not cells[0]:
        return "other"
    if any(_is_value(c) for c in cells[1:]):
        return "value"
    return "label"


def is_blank_form(lines: Sequence[tuple[int, str]]) -> bool:
    shapes = [line_shape(line) for _, line in lines]
    labels, values = shapes.count("label"), shapes.count("value")
    return labels >= MIN_LABEL_LINES and values <= labels * _VALUE_SHARE


def drop_label_lines(
    lines: Sequence[tuple[int, str]],
) -> list[tuple[int, str]]:
    """The heading-shaped lines only (cell-less lines)."""
    return [(pg, ln) for pg, ln in lines if line_shape(ln) == "other"]
