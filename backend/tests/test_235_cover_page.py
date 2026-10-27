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
from tests.test_165e_read_no_field import _coverage, _pdf
from tests.test_datasheet_ai import FakeModel, _ingest, _use, temp_storage  # noqa: F401

CLEAN_AI = {"pages": {1: {"accepted": [], "rejected": [], "counts": {}}}, "reasons": {}}
VISION_DOWN = "routed: no text-based reader found a field on this page, but the vision reader is unavailable (down)"


def _file(tmp_path, lines) -> str:
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(lines):
        page.insert_text((50, 80 + i * 20), line)
    path = tmp_path / "p.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


COVER = [
    "MECHANICAL DATASHEET",
    "Document no 0001-XX Rev 00 Sheet 1 of 8",
    "Issued for final",
]
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


def test_both_parts_of_the_check_must_hold():
    furniture = {row_noise.DOCUMENT_ID: 2, row_noise.REVISION: 1}
    assert cover_page.is_cover_or_notes(furniture, "TITLE Rev 00")
    assert cover_page.is_cover_or_notes({}, "TITLE Rev 00")  # no pairs, no quantity
    assert not cover_page.is_cover_or_notes(furniture, "Design pressure 23.5 barg")
    assert not cover_page.is_cover_or_notes({**furniture, "value gate": 1}, "TITLE")
    assert not cover_page.is_cover_or_notes(
        {"merged": 0, row_noise.MERGED_BLOCK: 1}, "TITLE"
    )
    assert not cover_page.is_cover_or_notes(furniture, None)
    assert not cover_page.is_cover_or_notes(furniture, "   ")


def test_a_page_read_clean_with_only_furniture_is_marked(tmp_path):
    path = _file(tmp_path, COVER)
    status, _n, why = page_ledger.no_fact(
        CLEAN_AI, 1, "x", {row_noise.DOCUMENT_ID: 2}, path
    )
    assert status == page_ledger.READ_NO_FIELD and cover_page.checked(why)


def test_a_page_with_a_measured_value_or_value_like_drop_is_not_marked(tmp_path):
    data = _file(tmp_path, DATA)
    assert not cover_page.checked(page_ledger.no_fact(CLEAN_AI, 1, "x", {}, data)[2])
    cover = _file(tmp_path, COVER)
    assert not cover_page.checked(
        page_ledger.no_fact(CLEAN_AI, 1, "x", {"value gate": 1}, cover)[2]
    )
    assert not cover_page.checked(page_ledger.no_fact(CLEAN_AI, 1, "x", {}, None)[2])


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
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
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
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
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
    doc = _ingest(_pdf(tmp_path / "d.pdf"))
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    _vision_down(doc)
    with db.connect() as conn:
        conn.execute(
            "UPDATE page_ledger SET ocr_status = 'failed' WHERE document_id = ? AND page_no = 1",
            (doc,),
        )
    cov = _coverage(doc)
    assert 1 in cov["pages_not_read_into_fields"] and cov["pages_read_no_field"] == []
