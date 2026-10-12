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
    most of its rows, and the invented set had no such table to say so (it
    has one now: `ds15`, below). Above a schedule's data, an answer row is
    one where EVERY cell after the label answers."""
    gutter = {0}
    header = ["1", "Mark", "Size", "Rating", "Flange type", "Service", "2"]
    assert g._states_a_value_beside_a_label(header, gutter)          # the loose test is fooled...
    assert not g._answers_in_every_cell(header, gutter)              # ...the strict one is not
    assert g._answers_in_every_cell(["", "Maximum flow", "150 m3/h", "150 m3/h"], gutter)
    assert not g._answers_in_every_cell(["", "Mark", "Size", "Rating"], gutter)


def test_the_invented_nozzle_schedule_keeps_its_header_and_every_row():
    table = _tables("ds15_vessel_nozzle_schedule.pdf")[0]
    assert table["headerless"] is False and table["header_rows"] == [0]
    assert table["labels"] == ["Mark", "Size", "Rating", "Flange type", "Service"]
    rows = dict(_table_rows("ds15_vessel_nozzle_schedule.pdf"))
    assert len(rows) == 16                                           # 4 marks x 4 columns
    assert rows["N1 Size"] == "4" and rows["N3 Flange type"] == "long weld neck"
    assert rows["N4 Service"] == "Drain"


def test_an_answer_row_cut_off_from_its_header_does_not_start_the_body():
    """THE SECOND REGRESSION THE REAL SHEETS CAUGHT (F1, 2026-10-11). A form
    page had its column names at the top, then section headings drawn inside
    the grid, then the rows. Starting the body at the first answering row cut
    the header off: the table was read as a plain label/value table and a
    clause-reference column became part of every name. The body may start at
    an answer row only when a header row sits directly on it, or nothing does."""
    box = (0.0, 0.0, 100.0, 10.0)
    cell = (0.0, 0.0, 30.0, 10.0)
    gutter: set[int] = set()
    header = ["Item", "Required", "Offered"]
    heading = ["Process data", "", ""]
    answer = ["Maximum flow", "150 m3/h", "150 m3/h"]
    rects = [[cell, cell, cell], [box, None, None], [cell, cell, cell]]
    assert g._is_title_row(rects[1], heading, gutter, 0.0, 100.0)
    # a section heading between the header and the answer row: no jump
    assert not g._header_sits_on(2, rects, [header, heading, answer], gutter, 0.0, 100.0)
    # one filled cell above that is not even a title: still not a header
    assert not g._header_sits_on(1, [rects[0], rects[2]], [["Note", "", ""], answer], gutter, 0.0, 100.0)
    # the header directly above, or nothing above (blank rows are nothing): jump
    assert g._header_sits_on(1, [rects[0], rects[2]], [header, answer], gutter, 0.0, 100.0)
    assert g._header_sits_on(0, [rects[2]], [answer], gutter, 0.0, 100.0)
    assert g._header_sits_on(1, [rects[0], rects[2]], [["", "", ""], answer], gutter, 0.0, 100.0)



def test_a_contents_row_is_layout_not_a_datasheet_value():
    """F1 on a real sheet (2026-10-11): a sheet's index table has the shape of
    a label/value table, and one of its rows was stored as a field - a section
    title with its page range. Read faithfully, and not a value of the
    equipment. A row whose label ends on the word for a sheet or a page and
    whose answer is only page numbers is dropped; everything else stays."""
    assert g._is_a_contents_row("Process and mechanical data Sht", "4 to 5")
    assert g._is_a_contents_row("Notes sheet", "6")
    assert g._is_a_contents_row("Drawings, pages:", "7 - 9")
    # a value with a unit, a value that is not only numbers, a label that is not a sheet
    assert not g._is_a_contents_row("Tube sheet", "25 mm")
    assert not g._is_a_contents_row("Tube sheet", "fixed")
    assert not g._is_a_contents_row("Operating pH", "4 to 5")
    assert not g._is_a_contents_row("Sheet size", "3")


def _lv_table(rows: list[list[str]]) -> dict:
    cell = lambda r, j, t: {"text": t, "column": j, "row": r, "page": 1, "bbox": (0, 0, 1, 1),   # noqa: E731
                            "value": t, "unit": None, "is_blank": False, "blank_marker": None,
                            "table_id": "p1-t1"}
    return {"rows": [{"cells": [cell(r, j, t) for j, t in enumerate(row)]} for r, row in enumerate(rows)]}


def test_a_headerless_table_emits_its_values_and_not_its_contents_rows():
    table = _lv_table([["Process and mechanical data Sht", "4 to 5"],
                       ["Operating pH", "4 to 5"],
                       ["Design pressure", "10 barg"]])
    rows = g._label_value_rows(table, lambda text: (0, 0))
    assert [(r["label"], r["value_text"]) for r in rows] == [
        ("Operating pH", "4 to 5"), ("Design pressure", "10 barg")]


def test_a_column_of_sheet_numbers_is_not_emitted_from_a_table_with_a_header():
    """The same row through the other door: the real index table HAS a header
    row, so its cell is labelled "<title> Sht" by the ordinary table path."""
    cell = lambda j, text, label: {"text": text, "column": j, "row": 1, "page": 1, "bbox": (0, 0, 1, 1),   # noqa: E731
                                   "value": text, "unit": None, "is_blank": False, "blank_marker": None,
                                   "table_id": "p1-t1", "label": label}
    table = {"headerless": False, "rows": [{"cells": [
        cell(0, "Process and mechanical data", "Contents"), cell(1, "4 to 5", "Sht"), cell(2, "B", "Rev")]}]}
    rows = g.read_page_rows(None, form={"pairs": []}, tables={"tables": [table]})
    assert [(r["label"], r["value_text"]) for r in rows] == [("Process and mechanical data Rev", "B")]
