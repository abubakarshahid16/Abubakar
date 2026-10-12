"""#695: table rows are extracted when the unit is in the cell, each table chunk
reads its own table, and skipped cells are counted. Ids M4941-M4949."""
from __future__ import annotations

from ._base import APP, Mutation

_T = "tests/test_w2b_695_table_rows.py"
_TAG = ("w2b", "tables")
_R = APP / "requirements_3b.py"
_S = APP / "standards.py"
_TB = APP / "tables.py"


def _m(i, desc, path, anchor, repl, kw):
    return Mutation(id=f"M{i}", phase=i, description=desc, path=path, anchor=anchor,
                    replacement=repl, target=_T, keyword=kw, tags=_TAG)


MUTATIONS: tuple[Mutation, ...] = (
    _m(4941, "a number with its own unit is not a value (the old reader)", _R,
       "    match = _CELL_WITH_UNIT.match(text)\n    if match is None:\n        return None\n",
       "    match = None\n    if match is None:\n        return None\n", "cell_reading or writes_its_units"),
    _m(4942, "range words count as units", _R,
       '_NOT_A_UNIT = frozenset({"x", "to", "and", "or", "of", "no", "na", "nil"})',
       "_NOT_A_UNIT = frozenset()", "still_refuses"),
    _m(4943, "the unit's origin is always said to be the column header", _S,
       '("cell" if cell_unit else "column_header")', '"column_header"', "writes_its_units"),
    _m(4944, "the column header's unit beats the cell's own", _S,
       "unit = cell_unit or requirements_3b.header_unit(column)",
       "unit = requirements_3b.header_unit(column) or cell_unit", "wins_over_the_column_header"),
    _m(4945, "a cell with a unit is not counted as skipped but silently lost: not_a_number is never counted", _S,
       '                    skipped["empty" if not raw_value else "not_a_number"] += 1\n',
       "", "counted_by_reason"),
    _m(4946, "rows without a label are lost without a count", _S,
       '                skipped["no_row_label"] += sum(1 for c in row[1:] if (c or "").strip())\n',
       "", "counted_by_reason"),
    _m(4947, "every table chunk on a page gets the largest table again", _TB,
       "        best = _table_of_chunk(tables, row[\"text\"])",
       "        best = max(tables, key=lambda t: sum(len(r) for r in t))", "own_table"),
    _m(4948, "the chunk text is never matched to a table's cells", _TB,
       "            return sum(1 for r in t for c in r if len(c) >= 2 and c in text)",
       "            return 0", "own_table or smaller_table"),
    _m(4949, "a chunk that matches no table is given the smallest one", _TB,
       "    return max(tables, key=size)\n\n\ndef parse_document_tables(",
       "    return min(tables, key=size)\n\n\ndef parse_document_tables(", "falls_back_to_the_largest"),
)
