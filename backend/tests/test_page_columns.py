"""Header line of unit-bearing names over numbers, and stacked labels (#1478, switch).

Public filled pump sheet, 1 Nov proof: the duty-point table (a line of names with
bracketed units, lines of numbers under it) gave no fact, and three stacked label
lines in one cell were joined into one jumbled label. Invented pages only.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import geometry_reader, page_columns
from app.config import settings


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "page_column_rows_enabled", True)


def _page(items):
    doc = pymupdf.open()
    page = doc.new_page()
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=10)
    return page


def _pairs(page):
    return {(r["label"], r["value_text"]) for r in geometry_reader.read_page_rows(page)
            if r["source"] == "form"}


#: One header line, two rows of numbers under it (invented names and values).
TWO_ROWS = [
    (60, 100, "TEST POINT"), (150, 100, "LOAD [kg]"), (230, 100, "LEVEL [m]"), (320, 100, "TEMP [bar]"),
    (66, 115, "1"), (155, 115, "812"), (232, 115, "6.5"), (322, 115, "11.2"),
    (66, 130, "2"), (155, 130, "905"), (232, 130, "7.1"), (322, 130, "12.4"),
]


def test_names_over_numbers_give_one_value_per_number(on):
    assert _pairs(_page(TWO_ROWS)) == {
        ("LOAD 1", "812 kg"), ("LEVEL 1", "6.5 m"), ("TEMP 1", "11.2 bar"),
        ("LOAD 2", "905 kg"), ("LEVEL 2", "7.1 m"), ("TEMP 2", "12.4 bar")}


def test_switch_off_reads_nothing_new():
    assert _pairs(_page(TWO_ROWS)) == set()


def test_a_single_row_keeps_the_plain_name(on):
    page = _page([i for i in TWO_ROWS if i[1] < 120])
    assert ("LOAD", "812 kg") in _pairs(page)
    assert not any(label.endswith(" 1") for label, _v in _pairs(page))


def test_row_number_is_not_a_value(on):
    labels = {label for label, _v in _pairs(_page(TWO_ROWS))}
    assert "TEST POINT 1" not in labels and len(labels) == 6


def test_a_number_in_brackets_beside_the_value_is_not_the_value(on):
    page = _page([*TWO_ROWS[:4], (155, 115, "812"), (190, 115, "(799)"), (232, 115, "6.5"), (322, 115, "11.2")])
    assert ("LOAD", "812 kg") in _pairs(page)
    assert ("LOAD", "799 kg") not in _pairs(page)


def test_one_name_alone_is_not_a_table(on):
    page = _page([(150, 100, "LOAD [kg]"), (155, 115, "812")])
    assert _pairs(page) == set()


def test_numbers_not_under_a_name_are_not_read(on):
    page = _page([*TWO_ROWS[:4], (500, 115, "812"), (540, 115, "6.5")])
    assert _pairs(page) == set()


def test_a_name_without_a_known_unit_is_not_a_head(on):
    page = _page([(150, 100, "LOAD [zzq]"), (230, 100, "LEVEL [m]"), (155, 115, "812"), (232, 115, "6.5")])
    assert _pairs(page) == set()


def test_a_number_another_reader_holds_is_not_read_twice():
    lines = [[(150, 100, 180, 110, "LOAD", 0, 0, 0), (182, 100, 195, 110, "[kg]", 0, 0, 0)],
             [(230, 100, 260, 110, "LEVEL", 0, 0, 0), (262, 100, 275, 110, "[m]", 0, 0, 0)],
             [(155, 115, 170, 125, "812", 0, 0, 0), (232, 115, 245, 125, "6.5", 0, 0, 0)]]
    # lines above are one line per head here, so build the header as one visual line
    head = lines[0] + lines[1]
    rows = page_columns.head_rows([head, lines[2]], lambda ln: [ln[i:i + 2] for i in range(0, len(ln), 2)],
                                  lambda text, allow_single=False: True, page_no=1,
                                  taken=[([150, 114, 175, 126], "812 kg")])
    assert [r["value_text"] for r in rows] == ["6.5 m"]


# --- stacked labels -----------------------------------------------------------

def test_three_short_capital_lines_are_stacked_labels():
    assert page_columns.is_stacked_labels("POWER FACTOR\nEFFICIENCY\nMOTOR DATA")


@pytest.mark.parametrize("raw", [
    "MAXIMUM ALLOWABLE\nWORKING PRESSURE",            # a wrapped label: two lines
    "Design pressure\nat the flange\nfor the vessel",  # sentence case wraps
    "1/1-LOAD\n0.82\n90.5 %\n---",                    # holds figures
    "FLOW",
    "",
    None,
])
def test_wrapped_labels_and_values_are_not_stacked(raw):
    assert not page_columns.is_stacked_labels(raw)


def test_stacked_cell_is_unreadable_only_with_the_switch(monkeypatch):
    raw = "POWER FACTOR\nEFFICIENCY\nMOTOR DATA"
    assert page_columns.clean_cell(raw, lambda c: " ".join(c.split())) == "POWER FACTOR EFFICIENCY MOTOR DATA"
    monkeypatch.setattr(settings, "page_column_rows_enabled", True)
    assert page_columns.clean_cell(raw, lambda c: " ".join(c.split())) == ""
    assert page_columns.clean_cell("Rated head\n14 m", lambda c: " ".join(c.split())) == "Rated head 14 m"


def test_default_is_off():
    assert settings.page_column_rows_enabled is False


class _Table:
    def __init__(self):
        self.rows = []

    def extract(self):
        return [["POWER FACTOR\nEFFICIENCY\nMOTOR DATA", "Max load\n14 kg"]]


def test_the_table_grid_never_joins_stacked_labels(monkeypatch):
    texts, _rects = geometry_reader._grid(_Table())
    assert texts == [["POWER FACTOR EFFICIENCY MOTOR DATA", "Max load 14 kg"]]
    monkeypatch.setattr(settings, "page_column_rows_enabled", True)
    texts, _rects = geometry_reader._grid(_Table())
    assert texts == [["", "Max load 14 kg"]]
