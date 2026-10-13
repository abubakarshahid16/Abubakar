"""PF1 (#881): the first row of a narrow label / value table may hold TEXT.

"Gas handled | Nitrogen" and "Service | Air receiver | Vacuum service | No"
were read as column NAMES. The row was lost, every other label grew its value
as a suffix ("casing design pressure nitrogen"), and on a four-column form a
LABEL became the value of another ("hydrostatic test pressure vacuum service
= Joint efficiency"); a longer name that contains the real label's words wins
the pairing, so a wrong value could stand for the field. On the invented PF1
set: 42 such junk fields, 3 lost rows; none on the three approved sheets.

Also: two label / value pairs on one row of a four-column form are two rows,
not one label made of both ("Shell plate material SA-285 Radiography" = 10 %).
Invented sheets drawn in the test; no model.
"""
from __future__ import annotations

import pymupdf
import pytest

from app import datasheets
from app import geometry_reader as g

FONT = 9


def _sheet(rows: list[list[str]], widths: list[int]):
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((40, 40), "DATASHEET", fontsize=12, fontname="hebo")
    y = 110
    for cells in rows:
        x = 40
        for width, cell in zip(widths, cells):
            page.draw_rect(pymupdf.Rect(x, y, x + width, y + 18), color=(0, 0, 0), width=0.6)
            if cell:
                page.insert_text((x + 4, y + 13), cell, fontsize=FONT)
            x += width
        y += 18
    return doc


def _rows(doc) -> list[tuple[str, str]]:
    return [(r["label"], r["value_text"]) for r in g.read_page_rows(doc[0]) if r["source"] == "table"]


# ------------------------------------------------------------------ the rule
@pytest.mark.parametrize("row, answer", [
    (["Gas handled", "Nitrogen"], True),
    (["Service", "Air receiver", "Vacuum service", "No"], True),
    (["Fluid", "Fuel gas"], True),
    (["Description", "Value"], False),
    (["Parameter", "Value", "Unit"], False),
    (["Item", "Required", "Offered", "Unit"], False),
    (["Ref", "Parameter", "Data", "UoM"], False),
    (["Item", "Vendor data"], False),
    (["Description", "Min", "Max", "Remarks"], False),
])
def test_a_first_row_is_an_answer_unless_it_consists_of_column_name_words(row, answer):
    below = [["Shell plate material", "SA-285", "Radiography", "10 %"], ["Manway size", "24 in", "Joint efficiency", "TBA"]]
    assert g._states_text_beside_a_label(row, set(), below) is answer


def test_a_four_column_first_row_with_unusual_header_words_is_a_header_unless_the_rows_below_are_two_pairs():
    """A header may use any words: "Attribute | Measure | Figure | Notes". Only
    rows below that are two label / value pairs, twice, make the first row an answer."""
    header = ["Attribute", "Measure", "Figure", "Notes"]
    schedule = [["Range", "bar", "40", "a"], ["Supply", "V", "24", "b"]]
    pairs = [["Shell plate material", "SA-285", "Radiography", "10 %"], ["Manway size", "24 in", "Joint efficiency", "TBA"]]
    assert g._states_text_beside_a_label(header, set(), schedule) is False
    assert g._states_text_beside_a_label(header, set(), []) is False
    assert g._states_text_beside_a_label(header, set(), pairs[:1]) is False
    assert g._states_text_beside_a_label(["Service", "Air receiver", "Vacuum service", "No"], set(), pairs) is True
    assert datasheets._first_row_states_a_value(["Service", "Air receiver", "Vacuum service", "No"], pairs) is True
    assert datasheets._first_row_states_a_value(header, schedule) is False


def test_a_three_column_table_keeps_its_first_row_as_the_header_whatever_the_words():
    assert g._states_text_beside_a_label(["Attribute", "Measure", "Figure"], set(), [["Range", "bar", "40"]]) is False
    assert g._states_text_beside_a_label(["Gas handled", "Nitrogen", "Note"], set(), []) is False


def test_a_wide_table_keeps_its_first_row_as_the_header():
    wide = ["Tag", "Service", "Fluid", "Pump", "Note"]
    assert g._states_text_beside_a_label(wide, set()) is False
    assert datasheets._first_row_states_a_value(wide) is False


# ------------------------------------------------------------------ the reading
def test_a_text_value_in_the_first_row_is_kept_and_names_nothing_else():
    """THE CASE of PF1's compressor sheet."""
    doc = _sheet([["Gas handled", "Nitrogen"], ["Casing design pressure", "40 barg"],
                  ["Discharge temperature", "195 degC"], ["Settle-out pressure", "42 barg"],
                  ["Surge margin", "12 %"], ["Head rise", "6 %"]], [190, 190])
    rows = _rows(doc)
    assert ("Gas handled", "Nitrogen") in rows
    assert ("Casing design pressure", "40 barg") in rows
    assert not [label for label, _v in rows if "nitrogen" in label.lower()], rows


def test_a_real_header_row_is_still_a_header():
    doc = _sheet([["Description", "Value"], ["Casing design pressure", "40 barg"], ["Discharge temperature", "195 degC"],
                  ["Settle-out pressure", "42 barg"], ["Surge margin", "12 %"], ["Head rise", "6 %"]], [190, 190])
    tables = g.read_tables(doc[0])["tables"]
    assert tables and tables[0]["headerless"] is False and tables[0]["header_rows"]


def test_a_four_column_form_gives_each_pair_its_own_row_and_never_a_label_made_of_both():
    doc = _sheet([["Service", "Air receiver", "Vacuum service", "No"],
                  ["Shell plate material", "SA-285 Grade C", "Radiography", "10 %"],
                  ["Hydrostatic test pressure", "24.7 barg", "Joint efficiency", "TBA"],
                  ["Manway size", "24 in", "Nozzle flange rating", "Class 150"]], [135, 120, 135, 90])
    rows = dict(_rows(doc))
    assert rows["Service"] == "Air receiver" and rows["Vacuum service"] == "No"
    assert rows["Shell plate material"] == "SA-285 Grade C" and rows["Radiography"] == "10 %"
    assert rows["Hydrostatic test pressure"] == "24.7 barg" and rows["Joint efficiency"] == "TBA"
    assert rows["Manway size"] == "24 in" and rows["Nozzle flange rating"] == "Class 150"
    # a label that is another label's value, or a label glued to its neighbour's, is a wrong fact
    assert not [label for label in rows if "vacuum service" in label.lower() and label.lower() != "vacuum service"], rows
    assert not [label for label in rows if label.lower().startswith("shell plate material ")], rows


def test_a_row_of_four_cells_whose_third_cell_is_a_number_is_one_row_as_before():
    """Not two pairs: "Pressure | design | 19 barg | note" has a value in cell 3."""
    doc = _sheet([["Pressure", "design", "19 barg", "note A"], ["Temperature", "design", "170 degC", "note B"]],
                 [110, 110, 110, 110])
    rows = _rows(doc)
    assert not any(label == "design" for label, _v in rows), rows
