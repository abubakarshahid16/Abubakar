"""Order 271.4 fix B: a text cell of a standards table is recorded with no value, only when the switch is on."""

from __future__ import annotations

import pytest

from app import comparison, standards, table_cells
from app.config import settings
from tests.test_standards_3b import (  # noqa: F401
    _chunk,
    _doc,
    _ruled_table_pdf,
    _scope,
    temp_storage,
)


def _extract(tmp_path, header, rows):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", header, rows)
    doc = _doc("doc_t", pdf)
    _chunk("c1", doc, "table text", kind="table", page=1)
    result = standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    return doc, result


def _rows(doc):
    return standards.list_requirements("doc_t", allowed_document_ids=_scope(doc))


TABLE = (
    ["Material", "Max temp (C)", "Remarks"],
    [["Carbon", "80", "Annealed"], ["Duplex", "120", "Quenched"]],
)


def test_with_the_switch_off_a_text_cell_is_skipped_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "table_text_cells_enabled", False)
    doc, result = _extract(tmp_path, *TABLE)
    assert {r["raw_value"] for r in _rows(doc)} == {"80", "120"}
    assert result["cells_skipped"]["not_a_number"] == 2


def test_with_the_switch_on_a_text_cell_is_recorded_with_no_value_and_a_citation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "table_text_cells_enabled", True)
    doc, result = _extract(tmp_path, *TABLE)
    by_raw = {r["raw_value"]: r for r in _rows(doc)}
    assert set(by_raw) == {"80", "120", "Annealed", "Quenched"}
    text = by_raw["Annealed"]
    assert text["value"] is None and text["unit"] is None and text["operator"] is None
    assert text["requirement_type"] == "table_value" and text["condition"] == "Carbon"
    assert text["page"] == 1 and text["chunk_id"] == "c1"  # a resolving citation
    assert text["source_text"] == "Carbon | Remarks | Annealed"
    assert result["values"] == 4 and result["cells_skipped"]["not_a_number"] == 0


def test_a_second_extraction_does_not_double_or_supersede_the_text_cells(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "table_text_cells_enabled", True)
    doc, _ = _extract(tmp_path, *TABLE)
    again = standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    assert again["superseded"] == 0 and again["merged_repeats"] == 4
    assert len(_rows(doc)) == 4


@pytest.mark.parametrize(
    "cell",
    ["", "-", "n/a", "N/A", "None", "(1)", "a", "Not applicable", "Carbon", "x" * 130],
)
def test_a_footnote_a_dash_a_repeated_label_or_a_paragraph_is_not_a_text_cell(cell):
    assert not table_cells.is_text_cell(cell, "Carbon")


@pytest.mark.parametrize("cell", ["Annealed", "Quenched", "Yes", "Max 30 ppm H2S"])
def test_a_word_entry_is_a_text_cell(cell):
    assert table_cells.is_text_cell(cell, "Duplex")


def test_a_text_cell_is_never_compared_to_a_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "table_text_cells_enabled", True)
    doc, _ = _extract(tmp_path, *TABLE)
    req = next(r for r in _rows(doc) if r["raw_value"] == "Annealed")
    fact = {
        "id": "f",
        "field_label": "Remarks",
        "field_value": "Annealed",
        "raw_value": "Annealed",
        "page": 1,
    }
    verdict = comparison.compare(req, fact)
    assert verdict["status"] == comparison.NEEDS_ENGINEER_REVIEW
    assert comparison.compare(req, None)["status"] == comparison.MISSING_INFORMATION


# The numeric half moved here from `standards.extract_table_values`; these pin what it returns.
def _numeric(cell, header):
    from app import requirements_3b

    reading = requirements_3b.cell_reading(cell)
    span = requirements_3b.cell_range(cell) if reading is None else None
    return table_cells.numeric_structured("Row", header, cell, reading, span, 1, "sig")


def test_a_unit_in_the_cell_and_its_operator_are_kept():
    row = _numeric(">= 5 mm", "Limit")
    assert (row["operator"], row["raw_unit"], row["unit_from"]) == (">=", "mm", "cell")
    assert row["requirement_type"] == "table_value" and row["value"] is not None


def test_a_bare_number_takes_the_column_header_unit_and_a_max_column_gives_less_or_equal():
    row = _numeric("500", "Max pressure (kPa)")
    assert (row["raw_unit"], row["unit_from"], row["operator"]) == (
        "kPa",
        "column_header",
        "<=",
    )


def test_a_number_with_no_unit_anywhere_keeps_its_value_and_claims_no_unit():
    row = _numeric("12", "Value")
    assert (row["value"], row["unit"], row["raw_unit"], row["unit_from"]) == (
        12.0,
        None,
        None,
        None,
    )


def test_a_range_is_one_requirement_with_two_bounds():
    row = _numeric("5-10", "Thickness (mm)")
    assert row["requirement_type"] == "table_range" and row["value"] is None
    assert (row["value_low"], row["value_high"], row["unit"]) == (
        5000.0,
        10000.0,
        "um",
    )  # the base unit
