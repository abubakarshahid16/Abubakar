"""#1473 (C1-4): a page is READ when a text reading came back for it, apart
from "fields found"; a Word file reaches the datasheet fact reader.

INVENTED documents only. The switch is PAGE_READ_BY_READING_ENABLED."""

from __future__ import annotations

import pytest

from app import (
    access,
    chunker,
    datasheet_inputs,
    datasheets,
    db,
    extract,
    fts_index,
    page_ledger,
    stored_paths,
    upload,
    word_flow,
)
from app.config import settings
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing

NOW = "2026-11-01T00:00:00Z"


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "c11473.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "datasheet_ai_reader", "off")
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    yield
    db.reset_connection()


def _prose_doc(pages: int = 3, *, ocr_pending: int | None = None) -> str:
    """A document whose pages are prose: no datasheet field on any of them."""
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO documents (id,filename,sha256,size_bytes,stored_path,status,"
            "page_count,uploaded_at) VALUES ('p1','p.pdf','sha-p',1,'x','ready',?,?)",
            (pages, NOW),
        )
        for n in range(1, pages + 1):
            pending = n == ocr_pending
            text = "" if pending else "Operators shall walk the line before start up."
            conn.execute(
                "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
                " VALUES ('p1',?,?,?,?,0)",
                (n, text, len(text), int(pending)),
            )
            conn.execute(
                "INSERT INTO chunks (id,document_id,filename,ordinal,page_start,page_end,"
                "section,kind,text,token_count,content_hash,retrievable)"
                " VALUES (?,?,?,?,?,?,NULL,'prose',?,1,?,1)",
                (f"c{n}", "p1", "p.pdf", n, n, n, text, f"h{n}"),
            )
        outcomes = dict.fromkeys(
            range(1, pages + 1), ("no_facts", 0, "no field was read from this page")
        )
        page_ledger.record_fact_pages(conn, "p1", outcomes, extractor_version="t")
    page_ledger.refresh("p1", as_submittal=True)
    return "p1"


def test_off_a_prose_page_is_unread_and_no_new_keys(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", False)
    cov = page_ledger.coverage(_prose_doc())
    assert cov["pages_not_read_into_fields"] == [1, 2, 3]
    assert "pages_read" not in cov and "pages_not_read" not in cov


def test_on_a_prose_page_is_read_but_fields_are_still_not_found(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    cov = page_ledger.coverage(_prose_doc())
    assert cov["pages_read"] == [1, 2, 3]
    assert cov["pages_not_read"] == []
    # "fields found" is a separate fact and is unchanged
    assert cov["pages_not_read_into_fields"] == [1, 2, 3]
    assert cov["fact_pages"] == []


def test_on_a_page_with_no_usable_text_stays_unread(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    cov = page_ledger.coverage(_prose_doc(ocr_pending=2))
    assert cov["pages_read"] == [1, 3]
    assert cov["pages_not_read"] == [2]


def test_run_unread_pages_follows_the_reading_when_the_run_stored_it():
    stored = {
        "pages_total": 3,
        "pages_not_read_into_fields": [1, 2, 3],
        "pages_not_read": [],
    }
    assert page_ledger.run_unread_pages(stored) == []
    old = {"pages_total": 3, "pages_not_read_into_fields": [1, 2, 3]}
    assert page_ledger.run_unread_pages(old) == [1, 2, 3]


def _word(tmp_path) -> str:
    body = (
        d.para("Purpose", style="Heading1")
        + d.para("Operators shall walk the line before start up.")
        + d.para("Step list", style="Heading1")
        + d.table([["Design pressure", "15 barg"], ["Set pressure", "12 barg"]])
    )
    path = d.build(tmp_path / "w.docx", body)
    with path.open("rb") as fh:
        row, _job, _dup = upload.ingest(fh, "w.docx")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    return row["id"]


def test_word_goes_to_the_fact_reader_only_with_the_switch(tmp_path, monkeypatch):
    doc = _word(tmp_path)
    path = stored_paths.of_document(doc)
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", False)
    assert not datasheet_inputs.is_office_input(path)
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    assert datasheet_inputs.is_office_input(path)
    assert not word_flow.applies(None)


def test_word_pages_are_the_pages_its_chunks_use_and_all_count_read(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    doc = _word(tmp_path)
    count = (
        db.connect()
        .execute("SELECT page_count FROM documents WHERE id=?", (doc,))
        .fetchone()[0]
    )
    pages = datasheet_inputs.office_pages(stored_paths.of_document(doc))
    assert len(pages) == count
    datasheets.extract_facts(doc, allowed_document_ids=frozenset({doc}))
    page_ledger.refresh(doc, as_submittal=True)
    cov = page_ledger.coverage(doc)
    assert cov["pages_total"] == len(pages)
    assert cov["pages_read"] == list(range(1, len(pages) + 1))
    assert cov["pages_not_read"] == []
    methods = {
        r[0]
        for r in db.connect().execute(
            "SELECT extraction_method FROM submittal_facts WHERE submittal_document_id=?",
            (doc,),
        )
    }
    assert methods == {"docx"}


def test_a_legacy_derived_no_facts_page_is_not_counted_read(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    doc = _prose_doc()
    with db.connect() as conn:  # extraction never recorded these pages
        conn.execute(
            "UPDATE page_ledger SET facts_recorded_by = 'derived' WHERE document_id=?",
            (doc,),
        )
    cov = page_ledger.coverage(doc)
    assert cov["pages_read"] == []
    assert cov["pages_not_read"] == [1, 2, 3]


def test_run_unread_pages_from_a_real_ledger(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    cov = page_ledger.coverage(_prose_doc(ocr_pending=2))
    assert page_ledger.run_unread_pages(cov) == [2]


def _doc_with_contents_page() -> str:
    """Three prose pages plus page 4, a contents page the indexer set aside."""
    doc = _prose_doc()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO pages (document_id,page_no,text,char_count,needs_ocr,batch_no)"
            " VALUES (?,4,'1 Scope 3',9,0,0)",
            (doc,),
        )
        conn.execute(
            "INSERT INTO exclusions (document_id,scope,page_start,page_end,chunk_id,rule,"
            "reason,text_sample,text_length,created_at,clause_headings)"
            " VALUES (?,'page',4,4,NULL,'page_classified_toc','contents','x',9,?,0)",
            (doc, NOW),
        )
    page_ledger.refresh(doc, as_submittal=True)
    return doc


def test_on_a_set_aside_contents_page_stays_unread_but_is_named(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    cov = page_ledger.coverage(_doc_with_contents_page())
    assert cov["pages_read"] == [1, 2, 3]
    assert cov["pages_not_read"] == [4]  # no reader ran: never counted read
    assert cov["pages_not_read_why"] == {
        "4": "excluded from the index on purpose (rule page_classified_toc)"
    }


def test_off_the_set_aside_key_is_absent(monkeypatch):
    monkeypatch.setattr(settings, "page_read_by_reading_enabled", False)
    cov = page_ledger.coverage(_doc_with_contents_page())
    assert "pages_not_read_why" not in cov


def test_the_crs_names_the_unread_page_and_why_and_the_summary_shows_not_read(
    monkeypatch,
):
    from app import crs_mapping, page_not_read

    monkeypatch.setattr(settings, "page_read_by_reading_enabled", True)
    cov = page_ledger.coverage(_doc_with_contents_page())
    outcome = {"page_coverage": cov}
    notes = crs_mapping.build_review_notes([], [], None, outcome)
    named = [n for n in notes if n["note"] == page_not_read.NOTE_PAGE_NOT_READ]
    assert len(named) == 1 and named[0]["count"] == 1
    assert "Page 4 was not read" in named[0]["detail"]
    assert (
        "excluded from the index on purpose (rule page_classified_toc)"
        in named[0]["detail"]
    )
    # the engineer's run summary lists it as not read, with the same words
    assert page_ledger.run_unread_pages(cov) == [4]
    assert page_ledger.run_unread_reasons(cov) == cov["pages_not_read_why"]
    # a run stored without the switch adds no note
    assert page_not_read.notes({"page_coverage": {}}) == []


def test_unread_page_words_blank_image_and_a_plain_failure():
    base = {
        "index_status": "retrievable",
        "index_reason": None,
        "native_status": "text",
        "ocr_status": "not_required",
        "facts_reason": None,
    }
    from app import page_not_read

    w = page_not_read.unread_page_words
    assert w({**base, "native_status": "empty"}) == "blank page"
    assert w({**base, "native_status": "needs_ocr", "ocr_status": "pending"}) == (
        "image with no reading"
    )
    # content that simply failed is not excused by any of the three kinds
    assert w({**base, "facts_reason": "the model failed"}) == "the model failed"
