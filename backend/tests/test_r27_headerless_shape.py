"""R27 (#830): a wide ruled table with NO header row is not read as if its
first rows were column names.

Measured on the invented merged-cell tank sheet. Its table is three columns
wide and starts with data: a group cell ("DESIGN") merged over two rows, a
sub-label, a value. `pairs_from_table_shape` takes row 0 of a wide table as
the header, so the first two DATA rows became "column names" and every field
below was named after their values ("Nominal capacity - 0.05 barg - 85 C" =
1500 m3), while the two rows themselves were lost. A value cell split in two
under one label ("Bottom course: 14 mm") was stored as a field whose value
was a sentence.

Now a wide table whose first row states a quantity has no header: each row
is its labels and its answer, a merged group cell is carried down, and a
value cell's own sub-label goes to the name.

Invented datasheets only.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app import datasheets, tables
from app import geometry_reader as g
from tests.test_datasheet_bench import BENCH, bench, key  # noqa: F401 - the fixture

DATA = Path(__file__).parent / "fixtures" / "synthetic" / "datasheets"
TANK = [["DESIGN", "Pressure", "0.05 barg"], ["", "Temperature", "85 °C"],
        ["GEOMETRY", "Diameter", "12000 mm"], ["", "Height", "14500 mm"],
        ["Nominal capacity", "", "1500 m3"], ["Roof type", "", "Fixed cone roof"],
        ["Shell plate thickness", "", "Bottom course: 14 mm"], ["", "", "Top course: 8 mm"]]


def test_the_merged_cell_table_is_read_row_by_row():
    assert datasheets.pairs_from_table_shape(TANK) == [
        ("DESIGN Pressure", "0.05 barg"), ("DESIGN Temperature", "85 °C"),
        ("GEOMETRY Diameter", "12000 mm"), ("GEOMETRY Height", "14500 mm"),
        ("Nominal capacity", "1500 m3"), ("Roof type", "Fixed cone roof"),
        ("Shell plate thickness Bottom course", "14 mm"), ("Shell plate thickness Top course", "8 mm")]


def test_no_field_is_named_after_another_rows_value():
    """THE DEFECT: "Nominal capacity - 0.05 barg - 85 C"."""
    for label, _value in datasheets.pairs_from_table_shape(TANK):
        assert "barg" not in label and "°C" not in label and " - " not in label


@pytest.mark.parametrize("row0, is_data", [
    (["DESIGN", "Pressure", "0.05 barg"], True),
    (["Design pressure", "", "23.5 barg"], True),
    (["Parameter", "Units", "Value"], False),              # column names
    (["Description", "Required", "Offered"], False),
    (["Mark", "Size", "Rating", "Service"], False),
    (["Item", "Rated (kW)", "Remarks"], False),            # a unit in a header is not a quantity
    (["1", "2", "3 mm"], False),                           # no label in front of it
    (["Only a caption", "", ""], False),
])
def test_what_makes_a_first_row_data(row0, is_data):
    assert datasheets._first_row_states_a_value(row0) is is_data


def test_a_table_with_a_real_header_row_is_read_exactly_as_before():
    grid = [["Parameter", "Units", "Value"], ["Rated power", "kW", "75"], ["Rated speed", "rpm", "1480"]]
    assert datasheets.pairs_from_table_shape(grid) == [
        ("Rated power - Value", "75 kW"), ("Rated speed - Value", "1480 rpm")]
    req_off = [["Description", "Required", "Offered"], ["Maximum flow", "150 m3/h", "160 m3/h"]]
    assert datasheets.pairs_from_table_shape(req_off) == [
        ("Maximum flow - Required", "150 m3/h"), ("Maximum flow - Offered", "160 m3/h")]


def test_a_sub_label_is_taken_only_from_a_value_that_states_a_number():
    rows = [["Design code", "", "API 650"], ["Remarks", "", "Note: see the hold list"],
            ["Shell plate thickness", "", "Bottom course: 14 mm"]]
    assert datasheets._pairs_from_headerless_shape(rows) == [
        ("Design code", "API 650"), ("Remarks", "Note: see the hold list"),
        ("Shell plate thickness Bottom course", "14 mm")]


def test_a_row_with_no_label_or_no_answer_yields_nothing():
    assert datasheets._pairs_from_headerless_shape([["", "", ""], ["", "", "12 mm"], ["Lonely label", "", ""]]) == []


def test_the_layout_reader_splits_the_same_value_cell():
    with pymupdf.open(str(DATA / "ds08_tank_merged_cells.pdf")) as doc:
        rows = {r["label"]: (r["value"], r["unit"], r["value_text"])
                for r in g.read_page_rows(doc[0]) if r["source"] == "table"}
    assert rows["Shell plate thickness Bottom course"] == ("14", "mm", "14 mm")
    assert rows["Shell plate thickness Top course"] == ("8", "mm", "8 mm")
    assert "Shell plate thickness" not in rows


def test_the_tank_sheet_end_to_end_has_every_field_and_nothing_extra(key):  # noqa: F811
    """Before: 10 of 10 found and 3 wrongly named values beside them."""
    shapes = tables.parse_page_tables(str(DATA / "ds08_tank_merged_cells.pdf"), 1)
    assert shapes and len(shapes[0][0]) == 3
    reading = bench.read_file_with("rules", BENCH / "ds08_tank_merged_cells.pdf")
    score = bench.score_file(key["files"]["ds08_tank_merged_cells.pdf"], reading["facts"])
    assert (score["found"], score["expected"], score["extra"], score["wrong_value"]) == (10, 10, 0, 0)
