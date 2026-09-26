"""The evidence that a submittal cites a standard: the right page, the right line.

MEASURED on a real datasheet before this fix: the citation sat at character 735
of a 741-character chunk spanning pages 4 and 5. The evidence published was
"page 4" and the first 200 characters of the chunk - the page header - so the
quote shown as proof of the citation did not contain the standard's number,
and the page it named did not carry it.

Synthetic documents only; the standard numbers are public ones.
"""
from __future__ import annotations

import pytest

from app import access, applicability, db
from app.config import settings

NOW = "2026-09-26T00:00:00Z"
SUB = "sub_ev"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "ev.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    db.reset_connection()
    db.init_db()
    yield
    db.reset_connection()


def _submittal(chunk_text: str, first: int, last: int, pages: dict[int, str]) -> None:
    with db.connect() as conn:
        conn.execute("""INSERT INTO documents
            (id,filename,sha256,size_bytes,stored_path,status,page_count,uploaded_at)
            VALUES (?,'sheet.pdf','sha-ev',1,'sheet.pdf','ready',?,?)""", (SUB, last, NOW))
        for page, text in pages.items():
            conn.execute("INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,"
                         "batch_no) VALUES (?,?,?,?,0,0)", (SUB, page, text, len(text)))
        conn.execute("""INSERT INTO chunks
            (id,document_id,filename,ordinal,page_start,page_end,section,kind,
             text,token_count,content_hash,retrievable)
            VALUES ('ev-c1',?,'sheet.pdf',0,?,?,NULL,'prose',?,1,'h-ev',1)""",
                     (SUB, first, last, chunk_text))


def _evidence(identifier: str = "API 610"):
    return applicability.citation_evidence(SUB, identifier, frozenset({SUB}))


HEADER = "MECHANICAL DATASHEET PUMP UNIT SHEET 4 OF 11 " * 6
PAGE_4 = HEADER + "\nDesign pressure : 16 barg\n"
PAGE_5 = "Inspection and testing\nPump design code :\nAPI 610\nHydrotest : Yes\n"


def test_the_page_is_the_one_whose_text_carries_the_citation():
    """The chunk spans pages 4 and 5; the citation is printed on page 5."""
    _submittal(" ".join((PAGE_4 + PAGE_5).split()), 4, 5, {4: PAGE_4, 5: PAGE_5})
    page, quote = _evidence()
    assert page == 5


def test_the_quote_is_the_printed_line_with_its_label():
    """A datasheet cell holds only the number; its label is the line above."""
    _submittal(" ".join((PAGE_4 + PAGE_5).split()), 4, 5, {4: PAGE_4, 5: PAGE_5})
    page, quote = _evidence()
    assert quote == "Pump design code : API 610"


def test_without_page_text_a_chunk_spanning_pages_claims_no_page():
    """Never a guessed page - but the quote still contains the citation."""
    _submittal(" ".join((PAGE_4 + PAGE_5).split()), 4, 5, {})
    page, quote = _evidence()
    assert page is None
    assert "API 610" in quote and len(quote) <= 200


def test_without_page_text_a_one_page_chunk_names_its_page():
    _submittal("GENERAL NOTES\nCasing per API 610 11th edition\nEND", 3, 3, {})
    assert _evidence() == (3, "Casing per API 610 11th edition")


def test_a_long_line_is_quoted_around_the_citation_not_from_its_start():
    long_line = ("x " * 300) + "the pump shall comply with API 610 in full " + ("y " * 300)
    _submittal(long_line, 2, 2, {2: long_line})
    page, quote = _evidence()
    assert page == 2 and "API 610" in quote and len(quote) <= 200


def test_a_standard_not_cited_has_no_evidence():
    _submittal(" ".join((PAGE_4 + PAGE_5).split()), 4, 5, {4: PAGE_4, 5: PAGE_5})
    assert _evidence("API 682") == (None, None)
