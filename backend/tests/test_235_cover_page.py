"""Order 235 item 3: a cover or notes page is read, not "unread".

With the picture reader unavailable the page ledger called every page the two
readers found no field on "not read", so a cover page (page 1) put UNREAD_PAGES
on every requirement the sheet did not state. Now a page is marked "no fields,
cover/notes page" when a text check holds: every dropped pair was page
furniture AND the page's own text has no measured value. Anything else, and
every page whose text layer was not usable, stays unread. Invented text only.
"""

from __future__ import annotations

import pymupdf
import pytest

from app import cover_page, datasheets, db, page_ledger, row_noise
from tests.test_165e_read_no_field import _coverage
from tests.test_datasheet_ai import FakeModel, _ingest, _use, temp_storage  # noqa: F401

CLEAN_AI = {"pages": {1: {"accepted": [], "rejected": [], "counts": {}}}, "reasons": {}}
VISION_DOWN = "routed: no text-based reader found a field on this page, but the vision reader is unavailable (down)"


def _file(tmp_path, lines, name="p.pdf") -> str:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((50, 80 + i * 20), line)
    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return str(path)


COVER = [
    "MECHANICAL DATASHEET",
    "Document no 0001-XX Rev 00 Sheet 1 of 8",
    "Issued for final",
]
#: Label and value pairs that every reader drops as page furniture (a title
#: block and a date): a cover page the check may mark.
FURNITURE_PAIRS = [("Document No", "0001-XX"), ("Date", "01/01/2024")]
DATA_ROWS = [("Design pressure", "23.5 barg"), ("Design temperature", "120 C")]


def _ruled_pdf(path, cover_pairs) -> str:
    """A ruled two-column cover page, then a ruled data page."""
    doc = pymupdf.open()
    for pairs in (cover_pairs, DATA_ROWS):
        page = doc.new_page(width=600, height=500)
        y = 60
        for label, value in pairs:
            page.draw_rect(
                pymupdf.Rect(40, y - 14, 300, y + 6), color=(0, 0, 0), width=0.7
            )
            page.draw_rect(
                pymupdf.Rect(300, y - 14, 560, y + 6), color=(0, 0, 0), width=0.7
            )
            page.insert_text((44, y), label, fontsize=9)
            page.insert_text((304, y), value, fontsize=9)
            y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


DATA = ["Notes", "Design pressure shall not exceed 23.5 barg at 120 C"]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Document no 0001-XX Rev 00 Sheet 1 of 8", False),
        ("Design pressure 23.5 barg", True),
        ("Design temperature 120 C", True),
        ("Flow 120 m3/h", True),
        ("Clause 5.3.2 applies, see note 4", False),
        ("2nd stage desalter", False),
        ("", False),
    ],
)
def test_a_measured_value_is_a_number_with_a_unit_the_system_knows(text, expected):
    assert cover_page.has_measured_value(text) is expected


def test_every_part_of_the_check_must_hold():
    furniture = {row_noise.DOCUMENT_ID: 2, row_noise.REVISION: 1}
    ok = ("TITLE Rev 00", False)
    assert cover_page.is_cover_or_notes(furniture, ok)
    assert not cover_page.is_cover_or_notes(
        furniture, ("Design pressure 23.5 barg", False)
    )
    assert not cover_page.is_cover_or_notes({**furniture, "value gate": 1}, ok)
    assert not cover_page.is_cover_or_notes({row_noise.MERGED_BLOCK: 1}, ok)
    assert not cover_page.is_cover_or_notes(furniture, None)
    assert not cover_page.is_cover_or_notes(furniture, ("   ", False))
    assert not cover_page.is_cover_or_notes(
        furniture, ("TITLE Rev 00", True)
    )  # a large picture


def test_a_page_where_no_pair_was_recovered_is_not_evidence_of_furniture():
    """cloud's ask on #1325: a notes or data page whose values are words (a
    material, "Class 300") has no number and unit; with no pair recovered at
    all it must stay unread."""
    words_only = ("Casing material: duplex stainless steel. Flange class 300.", False)
    assert not cover_page.is_cover_or_notes({}, words_only)
    assert not cover_page.is_cover_or_notes({"date": 0}, words_only)


def _no_fact(path, dropped):
    """`no_fact` as extraction calls it: inside an extraction (its page-failure
    record is set) that has noted the file."""
    token = datasheets._PAGE_FAILURES.set({})
    try:
        cover_page.remember(path)
        return page_ledger.no_fact(CLEAN_AI, 1, "x", dropped)
    finally:
        datasheets._PAGE_FAILURES.reset(token)


def test_a_page_read_clean_with_only_furniture_is_marked(tmp_path):
    status, _n, why = _no_fact(_file(tmp_path, COVER), {row_noise.DOCUMENT_ID: 2})
    assert status == page_ledger.READ_NO_FIELD and cover_page.checked(why)


def test_a_page_with_a_measured_value_or_value_like_drop_is_not_marked(tmp_path):
    data = _file(tmp_path, DATA, "data.pdf")
    cover = _file(tmp_path, COVER, "cover.pdf")
    assert not cover_page.checked(_no_fact(data, {row_noise.DOCUMENT_ID: 1})[2])
    assert not cover_page.checked(_no_fact(cover, {"value gate": 1})[2])
    assert not cover_page.checked(_no_fact(cover, {})[2])
    assert not cover_page.checked(_no_fact(None, {row_noise.DOCUMENT_ID: 1})[2])


def _with_picture(tmp_path, big: bool) -> str:
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=500)
    page.insert_text((50, 80), "Document no 0001-XX")
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
    pixmap.clear_with(200)
    size = 560 if big else 30
    page.insert_image(
        pymupdf.Rect(20, 100, 20 + size, 100 + min(size, 380)), pixmap=pixmap
    )
    path = tmp_path / ("big.pdf" if big else "logo.pdf")
    doc.save(str(path))
    doc.close()
    return str(path)


def test_a_page_with_a_large_picture_is_not_a_cover_page_but_a_logo_is(tmp_path):
    """cloud's ask on #1325: a text layer (a title block) beside a picture that
    may hold the values: the picture reader was needed, so the page stays
    unread. A small logo does not count."""
    furniture = {row_noise.DOCUMENT_ID: 1}
    assert not cover_page.checked(_no_fact(_with_picture(tmp_path, True), furniture)[2])
    assert cover_page.checked(_no_fact(_with_picture(tmp_path, False), furniture)[2])


def _vision_down(doc):
    with db.connect() as conn:
        conn.execute(
            "UPDATE page_ledger SET vision_status = 'not_attempted', vision_reason = ? "
            "WHERE document_id = ? AND page_no = 1",
            (VISION_DOWN, doc),
        )


def test_end_to_end_a_cover_page_is_read_when_the_picture_reader_is_down(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_ruled_pdf(tmp_path / "d.pdf", FURNITURE_PAIRS))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    assert cover_page.checked(page_ledger.rows(doc)[0]["facts_reason"])
    _vision_down(doc)
    cov = _coverage(doc)
    assert cov["pages_read_no_field"] == [1]
    assert cov["pages_not_read_into_fields"] == []


def test_an_unmarked_page_stays_unread_when_the_picture_reader_is_down(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_ruled_pdf(tmp_path / "d.pdf", FURNITURE_PAIRS))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    with db.connect() as conn:
        conn.execute(
            "UPDATE page_ledger SET facts_reason = 'Read, no checklist field found.' "
            "WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    _vision_down(doc)
    assert 1 in _coverage(doc)["pages_not_read_into_fields"]


def test_a_marked_page_whose_text_layer_was_not_usable_stays_unread(
    tmp_path, monkeypatch
):
    _use(monkeypatch, FakeModel([]))
    doc = _ingest(_ruled_pdf(tmp_path / "d.pdf", FURNITURE_PAIRS))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    _vision_down(doc)
    with db.connect() as conn:
        conn.execute(
            "UPDATE page_ledger SET ocr_status = 'failed' WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    cov = _coverage(doc)
    assert 1 in cov["pages_not_read_into_fields"] and cov["pages_read_no_field"] == []


def test_a_cover_page_that_also_carries_a_missed_field_stays_unread(tmp_path):
    """planner's ask on #1325: 'Casing material: Duplex SS', 'Flange rating:
    Class 300', 'Size: DN 50' beside a title block are fields the readers may
    have missed; title-block labels (document no, revision, date, sheet) are not."""
    furniture = {row_noise.DOCUMENT_ID: 1}
    title_block = [
        "Document No: 0001-XX",
        "Revision: 00",
        "Date: 01/01/2024",
        "Sheet: 1 of 8",
    ]
    assert cover_page.checked(
        _no_fact(_file(tmp_path, title_block, "tb.pdf"), furniture)[2]
    )
    for line in (
        "Casing material: Duplex SS",
        "Flange rating: Class 300",
        "Size: DN 50",
    ):
        path = _file(tmp_path, [*title_block, line], "f.pdf")
        assert not cover_page.checked(_no_fact(path, furniture)[2]), line
    assert cover_page.has_field_line("Material = Duplex") is True
    assert cover_page.has_field_line("Document no: 5") is False


def test_a_path_left_from_an_earlier_sheet_is_never_read_outside_an_extraction(
    tmp_path,
):
    path = _file(tmp_path, COVER)
    cover_page.remember(path)
    assert datasheets._PAGE_FAILURES.get() is None
    assert cover_page.page_view(1) is None


@pytest.mark.parametrize(
    "line",
    [
        "1. Casing material: Duplex SS",
        "2) Flange rating: Class 300",
        "(3) Size: DN 50",
        "- Casing material: Duplex",
        "* Flange rating: Class 300",
        "\u2022 Size: DN 50",
        "a) Casing material: Duplex",
        "1.1 Casing material: Duplex",
        "2.3.1 Size: DN 50",
        "1.1. Flange rating: Class 300",
    ],
)
def test_a_numbered_or_bulleted_field_line_is_still_a_field_line(line):
    """cloud-2's ask on #1325: notes pages are usually numbered or bulleted."""
    assert cover_page.has_field_line(line) is True
    # the same marker before a title-block label is not a field
    assert (
        cover_page.has_field_line(f"{line.split(' ')[0]} Document no: 0001-XX") is False
    )


def test_two_extractions_in_a_row_never_read_the_first_ones_file(tmp_path, monkeypatch):
    """The path is read only while an extraction runs, and each extraction notes
    its own file before any page is asked about."""
    _use(monkeypatch, FakeModel([]))
    first = _ingest(_ruled_pdf(tmp_path / "a.pdf", FURNITURE_PAIRS))
    datasheets.extract_facts(first, allowed_document_ids=frozenset({first}))
    assert datasheets._PAGE_FAILURES.get() is None and cover_page.page_view(1) is None
    plain = [
        ("Design pressure", "10 barg"),
        ("Design temperature", "50 C"),
        ("Tag", "P-1"),
    ]
    second = _ingest(_ruled_pdf(tmp_path / "b.pdf", plain), doc_id="DS-0002")
    datasheets.extract_facts(second, allowed_document_ids=frozenset({second}))
    assert not any(
        cover_page.checked(r["facts_reason"]) for r in page_ledger.rows(second)
    )
