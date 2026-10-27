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


def test_a_lone_number_before_a_label_is_an_index_not_an_answer():
    assert gi.is_index_before_label(
        ["Rated capacity", "", "8", "Orifice designation"], 2
    )
    assert not gi.is_index_before_label(["Pressure", "10 barg", "Fluid"], 1)
    assert not gi.is_index_before_label(["Pressure", "8"], 1)


def test_two_rows_are_not_enough_to_call_a_column_a_running_number():
    def row(n):
        return {
            "cells": [
                {"column": 0, "text": "Number of stages"},
                {"column": 1, "text": str(n)},
                {"column": 2, "text": "Stage type"},
            ]
        }

    table = {"rows": [row(2), row(4)]}
    assert gi.split(table) is table


def test_the_answer_skips_an_index_number_before_a_label():
    import re

    cells = [{"text": t} for t in ("Rated capacity", "", "8", "Orifice designation")]
    texts = [c["text"] for c in cells]
    got = gi.first_answer(cells, texts, [0, 2, 3], re.compile(r"^\d"))
    assert got is None
    cells[2]["text"] = texts[2] = "125 m3/h"
    assert gi.first_answer(cells, texts, [0, 2, 3], re.compile(r"^\d")) == 2


def test_a_numbered_column_must_grow_down_the_table():
    def row(n):
        return {
            "cells": [
                {"column": 0, "text": "Label"},
                {"column": 1, "text": str(n)},
                {"column": 2, "text": "Other label"},
            ]
        }

    same = {"rows": [row(4), row(4), row(4)]}
    assert gi.split(same) is same
    growing = {"rows": [row(2), row(4), row(6)]}
    assert gi.split(growing) is not growing
