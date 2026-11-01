"""A header-line row is read only when every name has exactly one number (#1478 review).

Reviewer cases that must give NO fact, the true case, and the loss counts that
reach the page ledger. Invented pages only.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import datasheets, geometry_reader, page_columns
from app.config import settings


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(settings, "page_column_rows_enabled", True)


@pytest.fixture
def failures():
    token = datasheets._PAGE_FAILURES.set({})
    yield datasheets._PAGE_FAILURES.get()
    datasheets._PAGE_FAILURES.reset(token)


def _page(items):
    page = pymupdf.open().new_page()
    for x, y, text in items:
        page.insert_text((x, y), text, fontsize=10)
    return page


def _pairs(page):
    return {
        (r["label"], r["value_text"])
        for r in geometry_reader.read_page_rows(page)
        if r["source"] == "form"
    }


HEADS = [
    (150, 100, "LOAD [kg]"),
    (230, 100, "LEVEL [m]"),
    (320, 100, "TEMP [bar]"),
]
TRUE_ROW = [(155, 115, "812"), (232, 115, "6.5"), (322, 115, "11.2")]


def test_the_true_row_is_still_read(on):
    assert _pairs(_page([*HEADS, *TRUE_ROW])) == {
        ("LOAD", "812 kg"),
        ("LEVEL", "6.5 m"),
        ("TEMP", "11.2 bar"),
    }


@pytest.mark.parametrize(
    "row",
    [
        [(155, 115, "2026"), (232, 115, "12"), (322, 115, "3")],  # a date, a year
        [(60, 115, "Page"), (155, 115, "5"), (232, 115, "12"), (322, 115, "3")],
        [(155, 115, "17.10"), (232, 115, "12"), (322, 115, "2014-10-17")],
        [(200, 115, "812"), (278, 115, "6.5"), (368, 115, "11.2")],  # shifted off
        [(155, 115, "812"), (232, 115, "6.5")],  # fewer numbers than names
        [(155, 115, "812"), (175, 115, "813"), (232, 115, "6.5"), (322, 115, "11.2")],
    ],
)
def test_a_row_that_is_not_one_number_per_name_gives_no_fact(on, row):
    assert _pairs(_page([*HEADS, *row])) == set()


def test_a_value_numparse_refuses_gives_no_fact(on, monkeypatch):
    monkeypatch.setattr(page_columns.numparse, "parse_value", lambda _t: None)
    assert _pairs(_page([*HEADS, *TRUE_ROW])) == set()


def test_a_skipped_row_does_not_stop_the_next_true_row(on, failures):
    page = _page(
        [
            *HEADS,
            (155, 115, "2026"),
            (232, 115, "12"),
            (322, 115, "3"),
            (155, 130, "812"),
            (232, 130, "6.5"),
            (322, 130, "11.2"),
        ]
    )
    assert ("LOAD", "812 kg") in _pairs(page)
    assert failures == {1: {"column rows: 1 value rows under a header line not read"}}


def test_stacked_label_cells_are_counted_on_the_page(on, failures):
    page_columns.clean_cell("POWER FACTOR\nEFFICIENCY\nMOTOR DATA", str)
    page_columns.clean_cell("A B\nC D\nE F", str)
    page_columns.with_head_rows(_page([]), [])
    assert failures == {1: {"column rows: 2 stacked label cells not read"}}


def test_a_cell_unit_that_differs_from_the_header_gives_no_fact(on, failures):
    page = _page(
        [
            (150, 100, "FLOW [l/s]"),
            (230, 100, "HEAD [m]"),
            (155, 115, "203"),
            (180, 115, "m3/h"),
            (232, 115, "14.5"),
        ]
    )
    assert _pairs(page) == set()
    assert failures == {
        1: {
            "column rows: 1 value rows whose unit in the cell differs from the header not read"
        }
    }


def test_the_same_unit_in_the_cell_is_read(on):
    page = _page(
        [
            (150, 100, "FLOW [l/s]"),
            (230, 100, "HEAD [m]"),
            (155, 115, "203"),
            (180, 115, "l/s"),
            (232, 115, "14.5"),
        ]
    )
    assert _pairs(page) == {("FLOW", "203 l/s"), ("HEAD", "14.5 m")}


def test_a_plain_number_takes_the_header_unit(on):
    page = _page(
        [
            (150, 100, "FLOW [l/s]"),
            (230, 100, "HEAD [m]"),
            (155, 115, "203"),
            (232, 115, "14.5"),
        ]
    )
    assert _pairs(page) == {("FLOW", "203 l/s"), ("HEAD", "14.5 m")}


def test_left_out_rows_reach_the_crs_note(on, failures):
    from app import page_ledger, page_not_read

    page = _page([*HEADS, (155, 115, "2026"), (232, 115, "12"), (322, 115, "3")])
    _pairs(page)
    page_columns.clean_cell("POWER FACTOR\nEFFICIENCY\nMOTOR DATA", str)
    page_columns.flush_losses(1)
    failed = {p: sorted(r) for p, r in failures.items()}
    assert failed
    pages = {"pages_total": 1, "pages_not_read_into_fields": []}
    gaps = page_ledger.reading_gaps({"page_failures": failed}, pages)
    notes = page_not_read.notes({"page_coverage": {"reading": gaps["reading"]}})
    assert [n["note"] for n in notes] == [page_not_read.NOTE_PAGE_READ_IN_PART]
    assert "page 1: column rows:" in notes[0]["detail"]
    assert "value rows under a header line not read" in notes[0]["detail"]


def test_a_page_already_not_read_is_not_also_read_in_part():
    from app import page_not_read

    cov = {
        "pages_not_read_why": {"1": "no reading came back for this page"},
        "reading": {
            "failed_pages": {
                "1": "a reader failed on this page (column rows: 1 stacked label cells not read)"
            }
        },
    }
    notes = page_not_read.notes({"page_coverage": cov})
    assert [n["note"] for n in notes] == [page_not_read.NOTE_PAGE_NOT_READ]
    cov["reading"]["failed_pages"]["2"] = (
        "a reader failed on this page (column rows: 1 stacked label cells not read)"
    )
    notes = page_not_read.notes({"page_coverage": cov})
    assert [n["detail"].startswith("page 2") for n in notes[1:]] == [True]


def test_no_note_when_the_gap_is_not_a_column_row_loss():
    from app import page_not_read

    failed = {"1": "a reader failed on this page (geometry)"}
    assert (
        page_not_read.notes({"page_coverage": {"reading": {"failed_pages": failed}}})
        == []
    )


def test_nothing_is_recorded_when_nothing_was_left_out(on, failures):
    _pairs(_page([*HEADS, *TRUE_ROW]))
    assert failures == {}
