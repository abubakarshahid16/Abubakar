"""The two follow-ups of #1324 (backlog 5): what an empty cell next to a label is NOT a blank for.

  * a label whose last word is a bare unit ("Design pressure barg") may be a value pushed into the
    label cell whose number was lost, so its empty neighbour proves nothing; a bracketed unit
    ("Design pressure (barg)") is an ordinary label and its empty cell still is a blank;
  * a solid DARK fill about the size of the one cell is a mark (blacked out: "not applicable"),
    not the background behind the table; a light fill (a shaded input cell) and a fill behind the
    whole table are still backgrounds.

Invented tables only, drawn with PyMuPDF (the builders of test_228_empty_cell_blank).
"""

from __future__ import annotations

import pymupdf
import pytest

from app import geometry_blank_cells as gb
from app import geometry_reader as g
from tests.test_228_empty_cell_blank import XS, _one_path_grid

ROWS = [
    ("Rated capacity", "125 m3/h"),
    ("Differential head", "85 m"),
    ("Design pressure", "10 barg"),
]


def _table(last_label: str, *, fill=None, fill_rect=None):
    rows = [*ROWS, (last_label, "")]
    doc, page = _one_path_grid(rows, XS)
    if fill is not None:
        top = 60 + 24 * 3
        rect = fill_rect or pymupdf.Rect(XS[1], top, XS[2], top + 24)
        page.draw_rect(rect, fill=fill, color=None)
    return doc, page


def _got(page):
    return {r["label"]: r for r in g.read_page_rows(page) if r["source"] == "table"}


@pytest.mark.parametrize(
    "label", ["Design pressure barg", "Rated power kW", "Test pressure psig"]
)
def test_a_label_ending_in_a_bare_unit_is_not_a_blank(label):
    doc, page = _table(label)
    try:
        assert label not in _got(page)
    finally:
        doc.close()


@pytest.mark.parametrize(
    "label",
    [
        "Design pressure (barg)",
        "Rated power [kW]",
        "Orifice designation",
        "Number of stages",
    ],
)
def test_a_bracketed_unit_or_no_unit_is_an_ordinary_label_and_still_a_blank(label):
    doc, page = _table(label)
    try:
        assert _got(page)[label]["is_blank"] is True
    finally:
        doc.close()


def test_the_bare_unit_rule_looks_at_the_last_word_and_at_two_words_or_more():
    assert gb._ends_in_a_bare_unit("Design pressure barg") is True
    assert gb._ends_in_a_bare_unit("Design pressure (barg)") is False
    assert gb._ends_in_a_bare_unit("barg") is False  # a lone word is a label of its own
    assert (
        gb._ends_in_a_bare_unit("Barg pressure") is False
    )  # a unit anywhere else is fine


def test_a_solid_black_fill_over_the_one_cell_is_a_mark_not_a_blank():
    doc, page = _table("Orifice designation", fill=(0, 0, 0))
    try:
        assert "Orifice designation" not in _got(page)
    finally:
        doc.close()


@pytest.mark.parametrize(
    "fill, big",
    [
        ((0.9, 0.9, 0.9), False),  # a shaded input cell is a cell to fill in
        ((1, 1, 1), False),
        ((0, 0, 0), True),  # a dark band behind the whole table is not this cell's mark
    ],
)
def test_a_light_fill_or_a_fill_behind_the_table_is_still_a_background(fill, big):
    rect = pymupdf.Rect(XS[0] - 5, 55, XS[2] + 5, 60 + 24 * 4 + 5) if big else None
    doc, page = _table("Orifice designation", fill=fill, fill_rect=rect)
    try:
        assert _got(page)["Orifice designation"]["is_blank"] is True
    finally:
        doc.close()


# cloud's and cloud-2's reviews of #1359 -----------------------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Operating temperature min",
        "Service hours",
        "Design life years",
        "Capacity per hr",
        "Inlet size in",
    ],
)
def test_a_label_ending_in_a_time_unit_or_a_preposition_word_is_an_ordinary_label(
    label,
):
    """A time unit at the end of a label names what the field COUNTS; "in" is also a word. Not a
    value lost into the label, so the empty cell is still a blank."""
    assert gb._ends_in_a_bare_unit(label) is False


INNER = (0.0, 0.0, 10.0, 10.0)  # area 100


@pytest.mark.parametrize(
    "fill, dark",
    [
        ((0.0, 0.0, 0.0), True),  # black
        ((0.34, 0.2, 0.1), True),  # every channel below 0.35
        ((0.35, 0.0, 0.0), False),  # the boundary: a channel AT 0.35 is not dark
        ((1.0, 0.0, 0.0), False),  # saturated red: a shaded input cell, not blacked out
        ((0.0, 1.0, 0.0), False),  # saturated green
        ((0.0, 0.0, 1.0), False),  # saturated blue
        ((0.1,), True),  # grey, one channel
        ((0.9,), False),
        (
            (0.0, 0.0, 0.0, 0.0),
            False,
        ),  # CMYK white (0,0,0,0) is NOT black: unknown model = background
        (None, False),
    ],
)
def test_the_fill_colour_rule(fill, dark):
    assert gb._dark_over_one_cell(INNER, (0.0, 0.0, 10.0, 10.0), {"fill": fill}) is dark


@pytest.mark.parametrize("width, one_cell", [(25.0, True), (25.1, False)])
def test_the_one_cell_size_limit_is_2_5_times_the_cell(width, one_cell):
    """A dark rectangle of 2.5 times the cell counts as this cell's mark; a hair more is a band."""
    assert (
        gb._dark_over_one_cell(INNER, (0.0, 0.0, width, 10.0), {"fill": (0, 0, 0)})
        is one_cell
    )
