"""Order 228.9b: a form printed as two numbered lists side by side.

Each row reads "N | label | value | N+1 | label | value". The label/value path
read only the first pair of a row, and a row whose first value cell was empty
took the next item's number as its value. Invented tables, drawn with PyMuPDF.
"""

from __future__ import annotations

import pymupdf

from app import geometry_index_cells as gi
from app import geometry_reader as g

XS = [30, 50, 200, 330, 350, 500, 630]
ROWS = [
    ("Design pressure", "10 barg", "Design temperature", "50 C"),
    ("Operating pressure", "8 barg", "Operating temperature", "40 C"),
    ("Set pressure", "9 barg", "Fluid", "Water"),
    ("Rated relieving capacity", "", "Orifice designation", ""),
    ("Effective area", "", "Calculated area", ""),
]


def _page(rows=ROWS):
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    ys = [60 + 24 * i for i in range(len(rows) + 1)]
    for y in ys:
        page.draw_line((XS[0], y), (XS[-1], y), width=0.6)
    for x in XS:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.6)
    n = 1
    for i, (a, b, c, d) in enumerate(rows):
        for xi, text in ((0, str(n)), (1, a), (2, b), (3, str(n + 1)), (4, c), (5, d)):
            if text:
                page.insert_text((XS[xi] + 3, ys[i] + 15), text, fontsize=9)
        n += 2
    return doc, page


def _read(rows=ROWS):
    doc, page = _page(rows)
    try:
        return {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}
    finally:
        doc.close()


def test_both_lists_of_a_side_by_side_form_are_read():
    got = _read()
    assert got["Design pressure"]["value_text"] == "10 barg"
    assert got["Design temperature"]["value_text"] == "50 C"
    assert got["Operating temperature"]["value_text"] == "40 C"
    assert got["Fluid"]["value_text"] == "Water"


def test_an_empty_value_cell_never_takes_the_next_items_number():
    got = _read()
    for label in ("Rated relieving capacity", "Effective area", "Orifice designation"):
        assert label not in got or got[label]["value_text"] in ("", None), got[label]


def _grid_read(rows, xs):
    doc = pymupdf.open()
    page = doc.new_page(width=842, height=595)
    ys = [60 + 24 * i for i in range(len(rows) + 1)]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y), width=0.6)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]), width=0.6)
    for i, cells in enumerate(rows):
        for j, text in enumerate(cells):
            if text:
                page.insert_text((xs[j] + 3, ys[i] + 15), text, fontsize=9)
    try:
        return {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}
    finally:
        doc.close()


def test_a_label_value_unit_table_reads_as_it_always_did():
    """cloud-2's reproduction: a whole number before a unit word is a value."""
    got = _grid_read(
        [
            ("Rated capacity", "125", "m3/h"),
            ("Wall thickness", "8", "mm"),
            ("Number of stages", "4", "pcs"),
            ("Design pressure", "10", "barg"),
            ("Design temperature", "120", "degC"),
        ],
        [50, 250, 350, 450],
    )
    assert got["Wall thickness"]["value_text"].startswith("8")
    assert got["Number of stages"]["value_text"].startswith("4")
    assert got["Design temperature"]["value_text"].startswith("120")
    assert not any(label.endswith(" 8") or label.endswith(" 4") for label in got), (
        sorted(got)
    )


def test_a_value_column_that_happens_to_grow_is_not_a_running_number():
    got = _grid_read(
        [
            ("Stages", "2", "pcs"),
            ("Wall thickness", "4", "mm"),
            ("Design pressure", "8", "barg"),
            ("Design temperature", "10", "degC"),
        ],
        [50, 250, 350, 450],
    )
    assert got["Design pressure"]["value_text"].startswith("8")
    assert got["Wall thickness"]["value_text"].startswith("4")


def _row(*texts):
    return {"cells": [{"column": i, "text": t} for i, t in enumerate(texts)]}


def test_two_rows_are_not_enough_to_call_a_column_a_running_number():
    table = {"rows": [_row("A", "1", "B", "2", "C"), _row("A", "3", "B", "4", "C")]}
    assert gi.split(table) is table


def test_a_numbered_column_must_grow_down_the_table():
    same = {"rows": [_row("1", "A", "2", "B")] * 3}
    assert gi.split(same) is same
    growing = {
        "rows": [
            _row("1", "A", "2", "B"),
            _row("3", "A", "4", "B"),
            _row("5", "A", "6", "B"),
        ]
    }
    assert gi.split(growing) is not growing


def test_a_column_beside_unrelated_numbers_is_not_a_running_number():
    table = {
        "rows": [
            {"cells": [{"column": 1, "text": "2"}, {"column": 2, "text": "6"}]},
            {"cells": [{"column": 1, "text": "4"}, {"column": 2, "text": "9"}]},
            {"cells": [{"column": 1, "text": "8"}, {"column": 2, "text": "12"}]},
        ]
    }
    assert gi.split(table) is table


def test_the_row_number_gutter_proves_the_column_beside_it():
    rows = [
        {
            "gutter": [str(n)],
            "cells": [{"column": 1, "text": "L"}, {"column": 2, "text": str(n + 1)}],
        }
        for n in (1, 3, 5)
    ]
    table = {"rows": rows}
    assert gi.split(table) is not table
    bare = {"rows": [{**r, "gutter": []} for r in rows]}
    assert gi.split(bare) is bare


def test_a_two_row_form_never_reads_the_next_items_number_as_a_value():
    """Numbering is not proven here (two rows), so the table is not cut; the
    empty answer must still not take the next item's number."""
    got = _grid_read(
        [
            ("Design pressure", "10 barg", "1", "Design temperature", "50 C"),
            ("Rated relieving capacity", "", "4", "Orifice designation", ""),
        ],
        [50, 200, 300, 330, 480, 600],
    )
    assert "Rated relieving capacity" not in got or got["Rated relieving capacity"][
        "value_text"
    ] in ("", None)
    assert not any(r["value_text"] == "4" for r in got.values()), got


def test_a_number_right_after_its_label_is_still_that_labels_value():
    got = _grid_read(
        [
            ("Number of stages", "4", "per the datasheet note"),
            ("Design pressure", "10 barg", "gauge"),
        ],
        [50, 250, 350, 600],
    )
    assert got["Number of stages"]["value_text"] == "4"


def test_text_in_the_numbered_column_is_not_dropped():
    def row(n, text):
        return {
            "cells": [
                {"column": 0, "text": "L"},
                {"column": 1, "text": text if text else str(n)},
                {"column": 2, "text": str(n + 1)},
            ]
        }

    rows = [row(1, ""), row(3, ""), row(5, ""), row(7, "NOTES: set pressure 9 barg")]
    out = gi.split({"rows": rows})["rows"]
    assert any(c["text"].startswith("NOTES") for r in out for c in r["cells"])
