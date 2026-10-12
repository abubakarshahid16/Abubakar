"""R27 (#830): a page stored with a rotation flag is read in ONE space.

PyMuPDF gives a page's text (words, blocks) in its UNROTATED space and finds
its tables in the space the page is DISPLAYED in. On a wide sheet filed the
usual way - drawn landscape, stored on a portrait page with a rotation flag -
the two disagree. Measured on an invented Required/Offered sheet before this
change: the layout reader found the grid and not one word inside it (0 rows),
and the text reader took the rows out of order and lost 2 of 8. A page whose
flag shows its text SIDEWAYS was worse: its table was read as one row of
"column names" (really the values) over one row of fields, and six values
were stored under names that began with a material.

Now the three readers that use positions (`tables`, `geometry_reader`,
`datasheets` text blocks and grid) turn the in-memory page so its text reads
left to right, and take words and tables from that one space. An ordinary
page - no flag, horizontal text - is not touched.

Invented datasheets only (`tests/fixtures/synthetic/datasheets`).
"""
from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app import datasheets, tables
from app import geometry_reader as g

DATA = Path(__file__).parent / "fixtures" / "synthetic" / "datasheets"
UPRIGHT = DATA / "ds04_control_valve_req_off.pdf"          # no flag
SIDEWAYS = DATA / "ds09_rotated_page.pdf"                  # drawn upright, flagged: shows sideways
LANDSCAPE = DATA / "ds16_fan_req_off_landscape.pdf"        # drawn landscape, flagged: shows upright


def _layout_rows(path) -> list[tuple[str, str]]:
    with pymupdf.open(str(path)) as doc:
        return [(r["label"], r["value_text"]) for r in g.read_page_rows(doc[0]) if r["source"] == "table"]


def _text_pairs(path) -> list[tuple[str, str]]:
    return datasheets._pairs_from_pdf_page(str(path), 1)


@pytest.mark.parametrize("path, stored, reads_at", [
    (UPRIGHT, 0, 0),
    (SIDEWAYS, 90, 0),          # the flag turned the text sideways: read it unturned
    (LANDSCAPE, 90, 90),        # the flag is what makes it readable: keep it
])
def test_the_rotation_a_page_is_read_at_is_the_one_its_text_is_written_in(path, stored, reads_at):
    with pymupdf.open(str(path)) as doc:
        page = doc[0]
        assert page.rotation == stored and g.text_rotation(page) == reads_at
        g.upright(page)
        assert page.rotation == reads_at


def test_an_ordinary_page_is_not_touched():
    with pymupdf.open(str(UPRIGHT)) as doc:
        page = doc[0]
        before = page.get_text("words")
        assert g.upright_words(page) == before and g.upright_blocks(page) == page.get_text("blocks")
        assert page.rotation == 0 and tuple(g.upright(page)) == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_a_page_with_no_text_keeps_its_rotation():
    doc = pymupdf.open()
    page = doc.new_page()
    page.set_rotation(90)
    assert g.text_rotation(page) == 90 and g.upright_words(page) == []


def test_the_landscape_sheet_is_read_by_the_layout_reader():
    """Before: 0 rows - the grid was found and no word lay inside it."""
    rows = dict(_layout_rows(LANDSCAPE))
    assert len(rows) == 16
    assert rows["Air flow Required"] == "42000 m3/h" and rows["Air flow Offered"] == "43500 m3/h"
    assert rows["Impeller diameter Offered"] == "1250 mm"


def test_the_landscape_sheets_words_lie_inside_its_table():
    with pymupdf.open(str(LANDSCAPE)) as doc:
        page = doc[0]
        words = g.upright_words(page)
        box = pymupdf.Rect(page.find_tables().tables[0].bbox)
        inside = [w for w in words if box.contains(pymupdf.Rect(w[:4]))]
        assert {"Air", "Required", "Offered", "43500"} <= {w[4] for w in inside}
        assert len(inside) >= 40


def test_the_landscape_sheets_text_rows_come_in_reading_order():
    labels = [label for label, _value in _text_pairs(LANDSCAPE)]
    wanted = ["Air flow", "Static pressure", "Shaft power", "Fan speed", "Inlet temperature",
              "Sound pressure level", "Impeller diameter", "Bearing life"]
    assert [label for label in labels if label in wanted] == wanted


def test_the_sideways_sheet_is_a_table_of_fields_not_one_row_of_values():
    """Before: `find_tables` saw 2 rows x 7 columns and six values were stored
    under names that began with the last row's value."""
    shapes = tables.parse_page_tables(str(SIDEWAYS), 1)
    assert len(shapes) == 1 and len(shapes[0]) == 7 and {len(row) for row in shapes[0]} == {2}
    assert shapes[0][0] == ["Design pressure", "19 barg"]
    assert shapes[0][-1] == ["Element material", "Stainless steel 316"]
    rows = dict(_layout_rows(SIDEWAYS))
    assert rows["Element material"] == "Stainless steel 316" and len(rows) == 7
    assert not [label for label in rows if label.startswith("Stainless")]


def _refiled(tmp_path, embed: int, flag: int) -> Path:
    """The upright sheet embedded turned by `embed` and stored with `flag`."""
    out = tmp_path / f"refiled_{embed}_{flag}.pdf"
    with pymupdf.open(str(UPRIGHT)) as src:
        doc = pymupdf.open()
        sideways = embed in (90, 270)
        size = (src[0].rect.height, src[0].rect.width) if sideways else (src[0].rect.width, src[0].rect.height)
        page = doc.new_page(width=size[0], height=size[1])
        page.show_pdf_page(page.rect, src, 0, rotate=embed)
        page.set_rotation(flag)
        doc.save(str(out))
        doc.close()
    return out


@pytest.mark.parametrize("embed, flag", [
    (90, 90), (270, 270), (180, 180),          # filed turned, flagged so it shows upright
    (90, 270), (270, 90), (180, 0), (90, 0),   # filed with the WRONG flag: shows upside down or sideways
])
def test_one_sheet_reads_the_same_however_it_is_filed(tmp_path, embed, flag):
    path = _refiled(tmp_path, embed, flag)
    assert _layout_rows(path) == _layout_rows(UPRIGHT)
    assert _text_pairs(path) == _text_pairs(UPRIGHT)
    assert tables.parse_page_tables(str(path), 1) == tables.parse_page_tables(str(UPRIGHT), 1)
