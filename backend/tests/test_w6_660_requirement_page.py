"""#660: a requirement cites the page its sentence is ON, not the first page of
the chunk that spans two. INVENTED text only.

Mutations: M4951-M4956, `python scripts/mutation_check.py --phase 4951`.
"""
from __future__ import annotations

from app import db, standards
from tests.test_standards_3b import _doc, _scope, temp_storage  # noqa: F401

PAGE1 = ("5.1 General\nThe pump casing shall be hydrostatically tested before dispatch to the site. "
         "Records of the test are kept by the manufacturer for the life of the order.")
PAGE2 = ("The coupling guard shall be made of non-sparking material and shall be removable "
         "for inspection without disturbing the driver alignment.\n"
         "The nameplate shall be of stainless steel and shall be fixed with rivets of the same material.")


def _spanning_chunk(doc, *, ordinal=0):
    """One chunk over pages 1 and 2, with the page texts stored as ingestion does."""
    with db.connect() as conn:
        for no, text in ((1, PAGE1), (2, PAGE2)):
            conn.execute("INSERT OR REPLACE INTO pages (document_id,page_no,text,char_count,batch_no)"
                         " VALUES (?,?,?,?,0)", (doc, no, text, len(text)))
        text = PAGE1 + "\n" + PAGE2
        conn.execute(
            "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,section,kind,"
            "text,token_count,content_hash,retrievable) VALUES ('span',?,?,?,1,2,'5.1 General','prose',?,?,?,1)",
            (doc, "STD-1.pdf", ordinal, text, len(text.split()), "h-span"))


def _pages_by_text(doc):
    rows = standards.list_requirements("doc_p", allowed_document_ids=_scope(doc))
    return {r["requirement_text"]: r["page"] for r in rows}


def test_a_requirement_on_the_second_page_of_a_spanning_chunk_cites_the_second_page():
    doc = _doc("doc_p", "x.pdf")
    _spanning_chunk(doc)
    standards.extract_requirements("doc_p", allowed_document_ids=_scope(doc))
    pages = _pages_by_text(doc)
    guard = next(p for t, p in pages.items() if "coupling guard" in t)
    nameplate = next(p for t, p in pages.items() if "nameplate" in t)
    casing = next(p for t, p in pages.items() if "hydrostatically" in t)
    assert guard == 2 and nameplate == 2
    assert casing == 1


def test_a_sentence_not_found_on_any_page_keeps_the_chunks_first_page():
    doc = _doc("doc_p", "x.pdf")
    _spanning_chunk(doc)
    chunk = {"page_start": 1, "page_end": 2}
    assert standards.sentence_page(chunk, "A sentence that is on neither page at all, anywhere.",
                                   {1: "abc", 2: "def"}) == 1


def test_a_one_page_chunk_is_not_searched():
    chunk = {"page_start": 4, "page_end": 4}
    assert standards.sentence_page(chunk, "The coupling guard shall be removable.", None) == 4


def test_line_breaks_and_hyphens_do_not_hide_a_sentence_from_its_page():
    chunk = {"page_start": 1, "page_end": 2}
    page2 = standards._fold_for_page("The coupling\nguard shall be made of non-\nsparking material")
    assert standards.sentence_page(
        chunk, "The coupling guard shall be made of non-sparking material",
        {1: standards._fold_for_page("other text entirely"), 2: page2}) == 2


def test_a_re_extraction_moves_a_kept_requirement_to_its_real_page():
    doc = _doc("doc_p", "x.pdf")
    _spanning_chunk(doc)
    standards.extract_requirements("doc_p", allowed_document_ids=_scope(doc))
    with db.connect() as conn:       # a row written before the fix: first page
        conn.execute("UPDATE standard_requirements SET page = 1")
    standards.extract_requirements("doc_p", allowed_document_ids=_scope(doc))
    pages = _pages_by_text(doc)
    assert next(p for t, p in pages.items() if "coupling guard" in t) == 2
