"""Cells of a standards table as requirement fields (`standards.extract_table_values`).

Order 271.4 fix B: a cell that is TEXT, not a number, as a requirement row.

`standards.extract_table_values` kept only the cells that read as a number, so a table of acceptable
materials, conditions or yes/no entries gave no rule at all (ISO 15156-3: one recorded table, 7 text cells,
0 number cells). With `TABLE_TEXT_CELLS_ENABLED` such a cell is recorded as a `table_value` whose value is
NULL and whose `raw_value` is the cell as written, quoted with its row label, column header and page. It
never decides anything by itself: `comparison.compare` answers "could not be read as a number, so no
comparison was made" when a value sits beside it and `table_gate` counts it, in one line per standard, when
the sheet has no field that answers it. The converter (270.3) and the engineer read it.

A cell is NOT recorded when it is a label repeated in a data column, a footnote marker, a dash or a
"not applicable", or longer than a cell should be (a paragraph cut into one cell is prose, not a table cell).
"""

from __future__ import annotations

import re

from . import numparse, requirements_3b

MAX_CHARS = 120
#: Entries that say nothing: a dash, a footnote marker, "n/a" and its spellings.
_EMPTY_WORDS = frozenset(
    {"n", "a", "na", "none", "nil", "not", "applicable", "see", "note", "notes"}
)
_LETTERS = re.compile(r"[^\W\d_]{2,}")


def is_text_cell(raw_value: str, row_label: str) -> bool:
    """Is this cell a statement worth recording?"""
    raw = (raw_value or "").strip()
    if (
        not raw
        or len(raw) > MAX_CHARS
        or numparse.fold(raw) == numparse.fold(row_label)
    ):
        return False
    words = _LETTERS.findall(raw)
    return bool(words) and not all(w.lower() in _EMPTY_WORDS for w in words)


def text_structured(
    label: str, column: str, raw_value: str, row_index: int, signature: str
) -> dict:
    """The row's structured fields: the shape of a numeric `table_value`, with no value."""
    return {
        "requirement_type": "table_value",
        "field": requirements_3b.field_name("", column),
        "condition": label,
        "operator": None,
        "raw_value": raw_value,
        "raw_unit": None,
        "unit_from": None,
        "value": None,
        "unit": None,
        "value_low": None,
        "value_high": None,
        "table_row": row_index,
        "identity_key": "\x1f".join(
            (
                signature,
                numparse.fold(label),
                numparse.fold(column),
                numparse.normalise_text(raw_value),
            )
        ),
    }


def numeric_structured(
    label: str,
    column: str,
    raw_value: str,
    reading,
    span,
    row_index: int,
    signature: str,
) -> dict:
    """The structured fields of a table cell that reads as a number, a number with a unit or a range
    (`reading` / `span` are `requirements_3b.cell_reading` / `cell_range`; exactly one is set)."""
    number_text, cell_unit = reading if reading is not None else ("", span.unit)
    unit = cell_unit or requirements_3b.header_unit(column)
    # #595 THE NUMBER COMES FROM numparse (decimal comma, sign,
    # thousands). A unit the table does not know leaves the value
    # NULL (never 0); a cell with no unit anywhere keeps the
    # number as written, with no unit.
    number, cell_operator = (
        requirements_3b.cell_number(number_text) if span is None else (None, None)
    )
    if span is not None:
        # #617: a range is ONE requirement with two bounds, never
        # one number. In the table's unit only when the unit is
        # known; an ambiguous dash keeps no bounds at all.
        low, high = span.low, span.high
        if unit and low is not None and high is not None:
            lo = requirements_3b.measure(f"{low:.12f}".rstrip("0").rstrip("."), unit)
            hi = requirements_3b.measure(f"{high:.12f}".rstrip("0").rstrip("."), unit)
            low, high = lo.normalized_value, hi.normalized_value
            normal_unit = (
                lo.normalized_unit if lo.normalized_value is not None else None
            )
            if low is None or high is None:
                low = high = None
        else:
            normal_unit = None
        value = None
    elif unit:
        # The parsed number goes in, not the cell's text: the unit
        # table reads the text with its own rules, numparse's
        # answer for a decimal comma is the one recorded here.
        measurement = requirements_3b.measure(
            "" if number is None else f"{number:.12f}".rstrip("0").rstrip("."), unit
        )
        value, normal_unit = (measurement.normalized_value, measurement.normalized_unit)
    else:
        value, normal_unit = number, None
    operator = (
        cell_operator or requirements_3b.header_operator(column)
        if span is None
        else (requirements_3b.RANGE_OPERATOR if span.low is not None else None)
    )
    field = requirements_3b.field_name("", column)
    # #594 IDENTITY: standard (the column below) + table (its
    # header) + row key + column + the value as written.
    identity = "\x1f".join(
        (
            signature,
            numparse.fold(label),
            numparse.fold(column),
            numparse.normalise_text(raw_value),
        )
    )
    return {
        "requirement_type": (
            "table_value" if span is None else requirements_3b.TABLE_RANGE
        ),
        "field": field,
        "condition": label,
        "operator": operator,
        "raw_value": raw_value,
        "raw_unit": unit,
        "unit_from": (("cell" if cell_unit else "column_header") if unit else None),
        "value": value,
        "unit": normal_unit,
        "value_low": low if span is not None else None,
        "value_high": high if span is not None else None,
        "table_row": row_index,
        "identity_key": identity,
    }
