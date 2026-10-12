"""The last lines kept nowhere (chunker v7).

Measured on the owner's corpus (2026-09-29, counts only): one standard had 35
of its 132 ruled tables read as ALL HEADER, which left no data rows, and the
whole table - caption included - reached no chunk (about 285 lines); and a
note printed inside a table's border, in no cell, was replaced by the table
and lost with it.
"""
from __future__ import annotations

from app import chunker as C


def _chunks(page_lines: list[str], tables: list[dict]):
    pages = [(1, "\n".join(page_lines))]
    running: set[str] = set()
    masked = C.mask_tables(pages, {1: tables}, running)
    kinds = {1: "prose"}
    blocks, _ = C.segment_document(masked, running, kinds)
    return C.build_chunks(blocks, C.document_vocabulary(pages))


PROSE = ["5.1 Materials",
         "Materials shall be selected from the table below for every service",
         "and shall be certified to the stated grade before fabrication starts."]


def test_a_table_read_as_all_header_keeps_its_text():
    lines = PROSE + ["Material Grade Remarks"]
    table = {"lines": [3], "rows": [["Material", "Grade", "Remarks"]]}
    text = " ".join(c.text for c in _chunks(lines, [table]))
    assert "Material" in text and "Grade" in text and "Remarks" in text


def test_a_note_inside_the_border_in_no_cell_is_kept():
    lines = PROSE + ["Service | Material", "Sour | Duplex",
                     "Note: hardness shall not exceed 22 HRC in sour service"]
    table = {"lines": [3, 4, 5], "rows": [["Service", "Material"], ["Sour", "Duplex"]]}
    text = " ".join(c.text for c in _chunks(lines, [table]))
    assert "22 HRC" in text
    assert "Duplex" in text


def test_a_normal_table_is_not_duplicated_as_notes():
    table = {"rows": [["Service", "Material"], ["Sour service", "Duplex steel"]],
             "raw": ["Service   Material", "Sour service   Duplex steel"]}
    assert C._raw_lines_in_no_cell(table) == []
    assert C._raw_lines_in_no_cell({"rows": [["A"]], "raw": ["x"]}) == []
