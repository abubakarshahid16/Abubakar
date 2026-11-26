"""A Word file's pictures read by the local OCR engine WITHOUT its pages (WORD_PICTURES_LOCAL_ENABLED; builder C, 26 Nov 2026).

The page switch (WORD_PAGE_MARKERS_ENABLED) also renumbers every Word file by its saved page breaks, so it stays off; the pictures are
read apart from it. A file with no stored picture reading must read exactly as before; a reading adds its text on the part the picture
sits in and moves no part. Invented values only.
"""

from __future__ import annotations

import dataclasses

import pytest

from app import access, db, docx_reader, extract, fts_index, word_pages, word_pictures
from app.aim_review import unread
from app.config import settings
from tests.fake_tokenizer import install_if_missing
from tests.test_word_page_markers import _ingest, _picture_doc, _run_job, _stub_engine


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "pages.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    monkeypatch.setattr(settings, "word_pictures_local_enabled", True)
    install_if_missing(monkeypatch)
    word_pages._CACHE.clear()
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    yield


def _shape(s) -> tuple:
    """Everything a reader of the structure sees, except the picture list."""
    return ([dataclasses.astuple(b) for b in s.blocks], [dataclasses.astuple(f) for f in s.furniture], s.pages, s.notes,
            s.pagination, s.proof)  # fmt: skip


def test_the_way_back_switch_is_on_by_default():
    assert type(settings).model_fields["word_pictures_local_enabled"].default is True
    assert type(settings).model_fields["word_page_markers_enabled"].default is False


def test_with_no_stored_reading_the_file_reads_exactly_as_with_the_switch_off(tmp_path, monkeypatch):
    path = _picture_doc(tmp_path)
    on = docx_reader.read_structure(path)
    monkeypatch.setattr(settings, "word_pictures_local_enabled", False)
    off = docx_reader.read_structure(path)
    assert _shape(on) == _shape(off)
    assert off.pictures == [] and [p.no for p in on.pictures] == [1, 2, 3]
    assert on.pagination is None and on.proof is None


def test_a_reading_adds_its_text_on_its_part_and_moves_no_part(tmp_path, monkeypatch):
    path = _picture_doc(tmp_path)
    monkeypatch.setattr(settings, "word_pictures_local_enabled", False)
    before = docx_reader.read_structure(path)
    monkeypatch.setattr(settings, "word_pictures_local_enabled", True)
    from app.docx_pages import PictureReading

    after = docx_reader.read_structure(path, picture_readings={1: PictureReading("Tank label")})
    assert len(after.pages) == len(before.pages)
    added = [b for b in after.blocks if b.text.startswith("[picture 1, read by OCR]")]
    assert [b.text for b in added] == ["[picture 1, read by OCR] Tank label"]
    # every block of before is still there, on the same part
    assert [dataclasses.astuple(b) for b in after.blocks if b not in added] == [dataclasses.astuple(b) for b in before.blocks]
    assert after.pagination is None and after.proof is None
    # the note counts one picture fewer not read
    n = next(int(x.split()[0]) for x in before.notes if "picture(s) or drawing(s) not read" in x)
    assert f"{n - 1} picture(s) or drawing(s) not read" in after.notes


def test_extraction_reads_the_pictures_with_the_page_switch_off(tmp_path, monkeypatch):
    path = _picture_doc(tmp_path)
    doc_id = _ingest(path)
    _run_job(doc_id)
    asked = _stub_engine(monkeypatch, {1: "Tank label"})
    extract.extract_document(doc_id)
    texts = [r[0] for r in db.connect().execute("SELECT text FROM pages WHERE document_id = ? ORDER BY page_no", (doc_id,))]
    assert asked == [1, 3]  # picture 2 is an EMF: not given to the engine, and said
    assert sum("[picture 1, read by OCR] Tank label" in t for t in texts) == 1


def test_the_way_back_reads_no_picture(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "word_pictures_local_enabled", False)
    path = _picture_doc(tmp_path)
    doc_id = _ingest(path)
    _run_job(doc_id)
    asked = _stub_engine(monkeypatch, {1: "Tank label"})
    extract.extract_document(doc_id)
    texts = [r[0] for r in db.connect().execute("SELECT text FROM pages WHERE document_id = ?", (doc_id,))]
    assert asked == [] and not any("read by OCR" in t for t in texts)
    assert word_pictures.read_document(path) == {"asked": 0}


def test_the_review_names_only_the_pictures_still_not_read(tmp_path, monkeypatch):
    path = _picture_doc(tmp_path)
    _stub_engine(monkeypatch, {1: "Tank label"})
    word_pictures.read_document(path)
    listed = unread._word_unread(db.connect(), path)
    assert [x["where"] for x in listed] == ["picture 2", "picture 3"]
    assert {x["why"] for x in listed} == {unread.PICTURE_NOT_READ}


def test_the_reindex_option_takes_only_the_word_files_that_hold_a_picture(tmp_path):
    import importlib.util
    from pathlib import Path

    from tests.test_word_page_markers import THREE_PAGES, _doc

    spec = importlib.util.spec_from_file_location("reindex_chunking", Path(__file__).resolve().parents[2] / "scripts" / "reindex_chunking.py")
    reindex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reindex)
    with_picture = _ingest(_picture_doc(tmp_path))
    _ingest(_doc(tmp_path, THREE_PAGES, pages=3, name="plain.docx"))
    listed = [d["document_id"] for d in reindex._survey(db.connect(), None, word_pictures=True)]
    assert listed == [with_picture]
