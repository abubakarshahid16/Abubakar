"""R27 (#504): a label/value table has no header row.

Found by the cell score (`scripts/table_cell_score.py`): when no row looked
like schedule data, the layout reader took a table's FIRST ROW as its header.
On a plain two-column datasheet table that row is already an answer, so it
was lost and every other row was named after its value ("Differential head
125 m3/h"). Now a first row that states a value beside a label makes the
table headerless: each row's label is its word cells (a group cell merged
from the row above included) and its answer is the cell that states a value.

Invented datasheets only (`tests/fixtures/synthetic/datasheets`).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf

from app import geometry_reader as g

DATA = Path(__file__).parent / "fixtures" / "synthetic" / "datasheets"


def _table_rows(name: str, page: int = 0) -> list[tuple[str, str]]:
    with pymupdf.open(str(DATA / name)) as doc:
        return [(r["label"], r["value_text"]) for r in g.read_page_rows(doc[page]) if r["source"] == "table"]


def _tables(name: str, page: int = 0) -> list[dict]:
    with pymupdf.open(str(DATA / name)) as doc:
        return g.read_tables(doc[page])["tables"]


def test_a_row_that_states_a_value_beside_a_label_is_an_answer_not_a_header():
    gutter: set[int] = set()
    assert g._states_a_value_beside_a_label(["Rated capacity", "125 m3/h"], gutter)
    assert g._states_a_value_beside_a_label(["Coupling type", "By Vendor"], gutter)      # a blank marker is an answer
    assert g._states_a_value_beside_a_label(["Minimum flow", "", "< 12 m3/h"], gutter)
    assert not g._states_a_value_beside_a_label(["Parameter", "Value", "Unit"], gutter)  # names columns
    assert not g._states_a_value_beside_a_label(["Item", "Description"], gutter)
    assert not g._states_a_value_beside_a_label(["10", "20"], gutter)                    # no label at all
    assert not g._states_a_value_beside_a_label(["Rated capacity", ""], gutter)


def test_the_first_row_of_a_two_column_table_is_kept_and_names_nothing_else():
    rows = _table_rows("ds01_pump_ruled.pdf")
    assert ("Rated capacity", "125 m3/h") in rows                  # the row that used to be the "header"
    assert ("Differential head", "85 m") in rows
    assert not [label for label, _value in rows if "125" in label], rows
    assert _tables("ds01_pump_ruled.pdf")[0]["headerless"] is True


def test_a_group_cell_merged_over_two_rows_names_both_and_a_sideways_merge_takes_nothing_from_above():
    rows = dict(_table_rows("ds08_tank_merged_cells.pdf"))
    assert rows["DESIGN Pressure"] == "0.05 barg"
    assert rows["DESIGN Temperature"] == "85 °C"                   # the group cell is drawn once, above
    assert rows["GEOMETRY Height"] == "14500 mm"
    # "Nominal capacity" spans the two label columns: nothing is pulled down into it
    assert rows["Nominal capacity"] == "1500 m3"
    assert rows["Roof type"] == "Fixed cone roof"                  # no number: the last filled cell answers


def test_a_table_with_a_real_header_row_still_uses_it():
    tables = _tables("ds05_motor_units_grid.pdf")
    assert tables and tables[0]["headerless"] is False and tables[0]["header_rows"]
    assert all(tables[0]["labels"])                                # its columns are named by the header


def test_the_answer_cell_carries_its_box_and_the_labels_box():
    with pymupdf.open(str(DATA / "ds01_pump_ruled.pdf")) as doc:
        row = next(r for r in g.read_page_rows(doc[0]) if r["label"] == "Rated capacity")
    assert row["bbox"] and row["label_bbox"] and row["bbox"][0] > row["label_bbox"][0]


def test_the_header_stops_at_the_first_row_that_already_answers():
    """A row of values WITH UNITS under a real header row is data, not a second
    header row: it was walked over (it holds no two plain numbers) and its
    values were glued to every column name - 14 extra fields on this sheet."""
    table = _tables("ds04_control_valve_req_off.pdf")[0]
    assert table["header_rows"] == [0] and table["labels"] == ["Description", "Required", "Offered"]
    assert table["headerless"] is False
    rows = dict(_table_rows("ds04_control_valve_req_off.pdf"))
    assert rows["Maximum flow Required"] == "150 m3/h"            # the row that used to be a header
    assert rows["Valve Cv Offered"] == "210"
    assert not [label for label in rows if "150 m3/h" in label], sorted(rows)


def test_a_header_row_with_one_number_in_it_is_still_a_header():
    """THE REGRESSION THE REAL SHEETS CAUGHT (F1, 2026-10-11). A schedule's
    header row can carry one number among its column names (a revision, a
    note mark). The first form of the rule above took "any cell states a
    value" as an answer row: a real nozzle schedule lost its column names and
    most of its rows, and the invented set had no such table to say so (one
    is written - `ds15` - and waits for the pre-commit hook to accept invented
    PDFs under backend/tests/fixtures/synthetic). Above a schedule's data, an
    answer row is one where EVERY cell after the label answers."""
    gutter = {0}
    header = ["1", "Mark", "Size", "Rating", "Flange type", "Service", "2"]
    assert g._states_a_value_beside_a_label(header, gutter)          # the loose test is fooled...
    assert not g._answers_in_every_cell(header, gutter)              # ...the strict one is not
    assert g._answers_in_every_cell(["", "Maximum flow", "150 m3/h", "150 m3/h"], gutter)
    assert not g._answers_in_every_cell(["", "Mark", "Size", "Rating"], gutter)
