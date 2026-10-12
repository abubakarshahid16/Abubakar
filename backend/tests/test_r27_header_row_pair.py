"""R27 (#830): a table's header row is not a field.

On a Required / Offered sheet the table reader takes row 0 as the column
names - and the text reader, walking the same page block by block, read the
same row as a pair: field "Description", value "Required". It was stored as
a fact on both invented Required/Offered sheets (1 extra value each).

A text pair is dropped only when BOTH sides are whole column names of the
SAME ruled table (three or more columns wide) on that page. A narrower shape
has no header row - its row 0 is a field like any other - so nothing of it
is ever dropped.

Invented datasheets only.
"""
from __future__ import annotations

import pytest

from app import datasheets
from tests.test_datasheet_bench import BENCH, bench, key  # noqa: F401 - the fixture

HEADER = datasheets.table_header_cells([["Description", "Required", "Offered"],
                                        ["Maximum flow", "150 m3/h", "150 m3/h"]])


def test_the_column_names_of_a_wide_table_are_its_header_cells():
    assert HEADER == {"description", "required", "offered"}


@pytest.mark.parametrize("shape", [
    [["Design pressure", "19 barg"], ["Design temperature", "120 C"]],          # two columns: row 0 is a field
    [["Maximum flow", "150 m3/h", "150 m3/h"], ["Valve Cv", "180", "210"]],     # row 0 states numbers: data
    [["Only one name", "", ""], ["Maximum flow", "150 m3/h", "150 m3/h"]],      # a caption, not column names
    [],
])
def test_a_shape_without_a_header_row_has_no_header_cells(shape):
    assert datasheets.table_header_cells(shape) == frozenset()


@pytest.mark.parametrize("pair, dropped", [
    (("Description", "Required"), True),
    (("Offered", "Required"), True),
    (("DESCRIPTION:", "Required"), True),            # folded like every field name
    (("Maximum flow", "150 m3/h"), False),           # a field and its value
    (("Description", "Globe valve"), False),         # a field that happens to be called Description
    (("Offered", ""), False),                        # one side only: not this rule's business
    (("Required", "150 m3/h"), False),
])
def test_only_a_pair_of_two_column_names_is_the_header_row(pair, dropped):
    assert datasheets.is_a_header_row_pair(pair, [HEADER]) is dropped


def test_the_two_names_must_be_of_the_same_table():
    other = datasheets.table_header_cells([["Mark", "Size", "Rating"], ["N1", "4", "150"]])
    assert not datasheets.is_a_header_row_pair(("Description", "Size"), [HEADER, other])
    assert datasheets.is_a_header_row_pair(("Mark", "Size"), [HEADER, other])
    assert not datasheets.is_a_header_row_pair(("Description", "Required"), [])


@pytest.mark.parametrize("name", ["ds04_control_valve_req_off.pdf", "ds16_fan_req_off_landscape.pdf"])
def test_the_header_row_is_not_stored_as_a_fact_on_a_required_offered_sheet(name, key):  # noqa: F811
    reading = bench.read_file_with("rules", BENCH / name)
    assert reading["status"] == "read"
    names = {datasheets.normalise_field_name(f["field"]) for f in reading["facts"]}
    assert "description" not in names
    score = bench.score_file(key["files"][name], reading["facts"])
    assert not [e for e in score["errors"] if e["field"] == "Description"]
    assert score["found"] >= 13 and score["wrong_value"] == 0
