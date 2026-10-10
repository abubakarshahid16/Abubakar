"""#617: a table cell holding a range ("5-10") is recorded as a range requirement.

Before: numparse gives no single number for "5-10", so the cell was skipped
(counted as not a number) and the limit never reached a review. Now it is ONE
requirement that keeps the cell as written, a low and a high bound parsed by
numparse, and the same table-cell identity as other cells. An ambiguous dash
("5 -10") keeps no bounds and goes to an engineer. INVENTED ruled tables only.

Mutations: M6301-M6308 (scripts/mutations/w2b_617_range_cells.py).
"""
from __future__ import annotations

from app import comparison, db, requirements_3b, standards
from tests.test_standards_3b import _chunk, _doc, _ruled_table_pdf, _scope, temp_storage  # noqa: F401


def _extract(tmp_path, header, rows):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", header, rows)
    doc = _doc("doc_t", pdf)
    _chunk("c1", doc, "table text", kind="table", page=1)
    result = standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    return doc, result


def _stored(doc_id):
    return [dict(r) for r in db.connect().execute(
        "SELECT requirement_type, operator, value, value_low, value_high, raw_value, unit, raw_unit,"
        " condition, identity_key FROM standard_requirements WHERE standard_document_id = ?"
        " ORDER BY table_row", (doc_id,))]


# ------------------------------------------------------------------ the reader


def test_a_range_cell_is_read_as_two_bounds():
    for cell, low, high, unit in (("5-10", 5, 10, None), ("5 - 10", 5, 10, None),
                                  ("5 to 10 mm", 5, 10, "mm"), ("5–10 %", 5, 10, "%"),
                                  ("2.5-3.5 bar", 2.5, 3.5, "bar")):
        span = requirements_3b.cell_range(cell)
        assert span is not None and not span.ambiguous, cell
        assert (span.low, span.high, span.unit) == (low, high, unit), cell


def test_an_ambiguous_dash_keeps_no_bounds():
    for cell in ("5 -10", "10-5", "5 - -10"):
        span = requirements_3b.cell_range(cell)
        assert span is not None and span.ambiguous, cell
        assert (span.low, span.high) == (None, None), cell


def test_what_is_not_a_range_is_not_read_as_one():
    for cell in ("5", "50 mm", "1-2-3", "A-10", "Grade B", "see 5-10 below", ""):
        assert requirements_3b.cell_range(cell) is None, cell


# ------------------------------------------------------------------ extraction


def test_a_range_cell_is_recorded_as_one_range_requirement(tmp_path):
    """THE MUTATION TARGET: before #617 the cell was skipped."""
    doc, result = _extract(tmp_path, ["Item", "Thickness (mm)"], [["Coating", "5-10"]])
    assert result["values"] == 1
    assert result["cells_skipped"]["not_a_number"] == 0
    [row] = _stored(doc)
    assert row["requirement_type"] == requirements_3b.TABLE_RANGE
    assert row["operator"] == requirements_3b.RANGE_OPERATOR
    low, high = requirements_3b.measure("5", "mm"), requirements_3b.measure("10", "mm")
    assert (row["value_low"], row["value_high"]) == (low.normalized_value, high.normalized_value)
    assert row["value"] is None, "a range was stored as one number"
    assert row["raw_value"] == "5-10"
    assert row["raw_unit"] == "mm" and row["unit"] == low.normalized_unit
    assert row["condition"] == "Coating"
    assert row["identity_key"] and row["identity_key"].endswith("5-10")


def test_a_range_with_its_own_unit_is_normalised(tmp_path):
    doc, _result = _extract(tmp_path, ["Item", "Pressure"], [["Test", "10 to 20 bar"]])
    [row] = _stored(doc)
    assert row["raw_unit"] == "bar"
    assert row["value_low"] is not None and row["value_high"] is not None
    assert row["value_low"] < row["value_high"]


def test_an_ambiguous_range_is_recorded_for_an_engineer_with_no_bounds(tmp_path):
    doc, _result = _extract(tmp_path, ["Item", "Limit"], [["Gap", "5 -10"]])
    [row] = _stored(doc)
    assert row["requirement_type"] == requirements_3b.TABLE_RANGE
    assert (row["value_low"], row["value_high"], row["value"], row["operator"]) == (None, None, None, None)
    assert row["raw_value"] == "5 -10"


def test_a_range_is_never_paired_as_a_single_number():
    assert not comparison.is_matchable({"requirement_type": requirements_3b.TABLE_RANGE, "raw_value": "5-10"})


def test_a_range_with_no_unit_keeps_its_numbers_as_written(tmp_path):
    doc, _ = _extract(tmp_path, ["Item", "Count"], [["Bolts", "4-8"]])
    [row] = _stored(doc)
    assert (row["value_low"], row["value_high"], row["unit"]) == (4.0, 8.0, None)


def test_re_extracting_a_range_does_not_duplicate_it(tmp_path):
    doc, _ = _extract(tmp_path, ["Item", "Thickness mm"], [["Coating", "5-10"]])
    standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    assert len([r for r in _stored(doc)]) == 1
