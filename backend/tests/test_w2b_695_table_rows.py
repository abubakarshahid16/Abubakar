"""#695: table rows were not extracted as requirements.

Two generic losses, both found by reading the code path on INVENTED ruled
tables (the labelled pilot sections are on the PC and are re-scored there):

  1. a cell that carries its own unit ("50 mm", "0.5 %", ">= 5 mm") was not a
     value, so every cell of a table that writes units in its cells was
     dropped without a trace;
  2. a page with two tables gave both table chunks the LARGEST table, so the
     smaller table's rows were never read.

And the extractor now says where the cells it did not record went.

Mutations: M4941-M4949, `python scripts/mutation_check.py --phase 4941`.
"""
from __future__ import annotations

from app import requirements_3b, standards, tables
from tests.test_standards_3b import _chunk, _doc, _ruled_table_pdf, _scope, temp_storage  # noqa: F401


def _rows(doc_id, doc):
    return standards.list_requirements(doc_id, allowed_document_ids=_scope(doc))


def _extract(tmp_path, header, rows):
    pdf = _ruled_table_pdf(tmp_path / "t.pdf", header, rows)
    doc = _doc("doc_t", pdf)
    _chunk("c1", doc, "table text", kind="table", page=1)
    result = standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    return doc, result


# ------------------------------------------------ 1. a unit written in the cell

def test_cell_reading_separates_the_number_from_its_own_unit():
    assert requirements_3b.cell_reading("50") == ("50", None)
    assert requirements_3b.cell_reading("50 mm") == ("50", "mm")
    assert requirements_3b.cell_reading("0.5 %") == ("0.5", "%")
    assert requirements_3b.cell_reading(">= 5 mm") == (">= 5", "mm")
    assert requirements_3b.cell_reading("12.5 °C") == ("12.5", "°C")
    assert requirements_3b.cell_reading("90 dB(A)") == ("90", "dB(A)")


def test_cell_reading_still_refuses_what_is_not_a_value():
    for cell in ("", "-", "N/A", "Grade B", "A106", "see 5.2", "10 to 20", "10-20",
                 "1.5 x", "Not required"):
        assert requirements_3b.cell_reading(cell) is None, cell


def test_a_table_that_writes_its_units_in_the_cells_is_extracted(tmp_path):
    doc, result = _extract(tmp_path, ["Item", "Limit"],
                           [["Wall thickness", "50 mm"], ["Moisture", "0.5 %"],
                            ["Minimum cover", ">= 5 mm"]])
    rows = {r["condition"]: r for r in _rows("doc_t", doc)}
    assert set(rows) == {"Wall thickness", "Moisture", "Minimum cover"}
    wall = rows["Wall thickness"]
    assert wall["raw_value"] == "50 mm" and wall["raw_unit"] == "mm"
    assert wall["unit_from"] == "cell"
    assert wall["value"] is not None and wall["value"] > 0     # normalised, not the raw 50
    assert rows["Minimum cover"]["operator"] == ">="
    assert result["values"] == 3 and result["cells_skipped"]["not_a_number"] == 0


def test_a_unit_in_the_cell_wins_over_the_column_header(tmp_path):
    doc, _ = _extract(tmp_path, ["Item", "Limit (kPa)"], [["Test pressure", "5 bar"]])
    row = _rows("doc_t", doc)[0]
    assert row["raw_unit"] == "bar" and row["unit_from"] == "cell"


def test_a_bare_number_still_takes_its_unit_from_the_column_header(tmp_path):
    doc, _ = _extract(tmp_path, ["Item", "Limit (kPa)"], [["Test pressure", "500"]])
    row = _rows("doc_t", doc)[0]
    assert row["raw_unit"] == "kPa" and row["unit_from"] == "column_header"


# ------------------------------------------- 2. the cells that are not recorded

def test_cells_that_are_not_recorded_are_counted_by_reason(tmp_path):
    doc, result = _extract(tmp_path, ["Item", "Limit", "Note"],
                           [["Wall", "50 mm", "Grade B"], ["Cover", "N/A", "10 to 20"],
                            ["", "12", "13"]])
    assert result["values"] == 1                       # only "50 mm"
    skipped = result["cells_skipped"]
    assert skipped["not_a_number"] == 3                # Grade B, N/A, 10 to 20
    assert skipped["no_row_label"] == 2                # the row with no label: "12" and "13"
    assert skipped["empty"] == 0


# --------------------------------------------------- 3. two tables on one page

def _two_tables_pdf(path):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)

    def draw(y0, header, rows, width):
        for r, row in enumerate([header, *rows]):
            for c, cell in enumerate(row):
                rect = pymupdf.Rect(40 + c * width, y0 + r * 30, 40 + (c + 1) * width, y0 + (r + 1) * 30)
                page.draw_rect(rect, color=(0, 0, 0), width=0.7)
                page.insert_text((rect.x0 + 4, rect.y0 + 19), str(cell), fontsize=9)

    draw(40, ["Pipe size", "Wall", "Mass", "Pressure"],
         [["DN 50", "3.20", "5.10", "10.5"], ["DN 80", "4.00", "8.20", "12.5"], ["DN 100", "5.00", "11.4", "14.5"]], 120)
    draw(300, ["Grade", "Yield"], [["Grade A", "240"], ["Grade B", "275"]], 120)
    doc.save(str(path))
    doc.close()
    return str(path)


def test_each_table_chunk_on_a_page_gets_its_own_table(tmp_path):
    pdf = _two_tables_pdf(tmp_path / "two.pdf")
    doc = _doc("doc_t", pdf)
    _chunk("big", doc, "Pipe size Wall Mass Pressure DN 50 3.20 5.10 10.5 DN 80 4.00 8.20 12.5 DN 100 5.00 11.4 14.5",
           kind="table", page=1, ordinal=0)
    _chunk("small", doc, "Grade Yield Grade A 240 Grade B 275", kind="table", page=1, ordinal=1)
    parses = {p.chunk_id: p for p in tables.parse_document_tables("doc_t", allowed_document_ids=_scope(doc))}
    assert parses["big"].columns == ["Pipe size", "Wall", "Mass", "Pressure"]
    assert parses["small"].columns == ["Grade", "Yield"]


def test_the_smaller_table_on_a_page_is_extracted_too(tmp_path):
    pdf = _two_tables_pdf(tmp_path / "two.pdf")
    doc = _doc("doc_t", pdf)
    _chunk("big", doc, "Pipe size Wall Mass Pressure DN 50 3.20 5.10 10.5 DN 80 4.00 8.20 12.5 DN 100 5.00 11.4 14.5",
           kind="table", page=1, ordinal=0)
    _chunk("small", doc, "Grade Yield Grade A 240 Grade B 275", kind="table", page=1, ordinal=1)
    standards.extract_table_values("doc_t", allowed_document_ids=_scope(doc))
    raw = {r["raw_value"] for r in _rows("doc_t", doc)}
    assert {"240", "275"} <= raw                 # the second table
    assert {"3.20", "14.5"} <= raw                    # the first, still
    by_chunk = {r["chunk_id"] for r in _rows("doc_t", doc)}
    assert by_chunk == {"big", "small"}


def test_a_chunk_that_matches_no_table_falls_back_to_the_largest(tmp_path):
    pdf = _two_tables_pdf(tmp_path / "two.pdf")
    doc = _doc("doc_t", pdf)
    _chunk("odd", doc, "completely unrelated words", kind="table", page=1)
    parse = tables.parse_document_tables("doc_t", allowed_document_ids=_scope(doc))[0]
    assert parse.columns == ["Pipe size", "Wall", "Mass", "Pressure"]
