"""Order 228.4: a row with no datasheet page says "Not read from the datasheet (N pages)", with the field and
at most three tags, instead of the field and every tag of its group (300+ characters).
Invented documents only."""

from __future__ import annotations

import uuid

import pytest

from app import crs_mapping, crs_page_words, db
from app.config import settings

NOW = "2026-10-26T00:00:00"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "t.sqlite")
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _sheet(pages: int, stored_pages: int | None = None) -> str:
    """A submittal whose record says `pages` pages and that holds `stored_pages` page rows
    (default: the same). The two differ on a scan or when a page row is missing."""
    doc = str(uuid.uuid4())
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)"
            " VALUES (?,?,?,1,'/x','ready',?,?)",
            (doc, "sheet.pdf", f"sha-{doc}", pages, NOW),
        )
        for n in range(1, (pages if stored_pages is None else stored_pages) + 1):
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,batch_no) VALUES (?,?,?,?,0)",
                (doc, n, "x", 1),
            )
    return doc


def _finding(doc: str, tag: str, **over) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "document_id": doc,
        "equipment_tag": tag,
        "crs_field_label": "Rated capacity",
        "contractor_section": "Rated capacity",
        "contractor_page": None,
        "fact_id": None,
        **over,
    }


def test_a_value_not_found_names_the_pages_looked_at_and_cuts_the_tag_list():
    doc = _sheet(5)
    group = [_finding(doc, f"PSV-{n}") for n in range(1, 41)]
    cell = crs_mapping._page_section(group)
    assert (
        cell
        == "Not read from the datasheet (5 pages) - Rated capacity (PSV-1, PSV-2, PSV-3 and 37 more)"
    )
    assert len(cell) < 90


def test_a_row_with_a_page_prints_exactly_what_it_printed_before():
    doc = _sheet(5)
    group = [_finding(doc, "V-2001", contractor_page=2, fact_id="f1")]
    assert crs_mapping._page_section(group) == "p.2 - Rated capacity (V-2001)"
    two = [
        _finding(doc, "A", contractor_page=1, fact_id="f1"),
        _finding(doc, "B", contractor_page=3, fact_id="f2"),
    ]
    assert (
        crs_mapping._page_section(two)
        == f"p.{crs_mapping._page_list([1, 3])} - Rated capacity (A, B)"
    )


def test_a_value_that_was_read_but_has_no_page_is_never_called_not_read():
    doc = _sheet(5)
    group = [_finding(doc, "V-2001", fact_id="f1")]
    cell = crs_mapping._page_section(group)
    assert "Not read" not in cell and "Rated capacity" in cell


def test_the_count_is_the_documents_size_never_a_claim_that_its_pages_were_searched():
    assert (
        crs_page_words.where([], "", "Size", [], {_sheet(1)}, False)
        == "Not read from the datasheet (1 page) - Size"
    )
    assert (
        crs_page_words.where([], "", "Size", [], {_sheet(12)}, False)
        == "Not read from the datasheet (12 pages) - Size"
    )
    assert (
        crs_page_words.where([], "", "Size", [], {None}, False)
        == "Not read from the datasheet - Size"
    )
    assert (
        crs_page_words.where([], "", "Size", [], {"no-such-document"}, False)
        == "Not read from the datasheet - Size"
    )


def test_a_group_that_spans_several_documents_says_so_and_gives_no_count():
    cell = crs_page_words.where([], "", "Size", [], {_sheet(5), _sheet(7)}, False)
    assert cell == "Not read from the datasheets - Size"


def test_a_row_with_no_field_no_tag_and_no_page_stays_empty():
    assert crs_page_words.where([], "", "", [], {_sheet(3)}, False) == ""


def test_the_documents_own_page_count_wins_over_the_number_of_page_rows():
    """A scan or a missing page row must not shorten the count: the record says 9 pages."""
    assert crs_page_words.where(
        [], "", "Size", [], {_sheet(9, stored_pages=6)}, False
    ) == ("Not read from the datasheet (9 pages) - Size")


def test_the_page_rows_are_counted_only_when_the_record_has_no_count():
    assert crs_page_words.where(
        [], "", "Size", [], {_sheet(0, stored_pages=4)}, False
    ) == ("Not read from the datasheet (4 pages) - Size")
