"""W5b-01 (#525): a Word (.docx) document goes through the SAME pipeline as a
PDF with its structure kept. INVENTED documents only (tests/docx_builder.py).

The pipeline stages that need model weights (embedding) are not run here; what
is proved is the reader, the upload gate, extraction, chunking, the chunk
rows and the keyword side of search, which are everything this change touches.
"""
from __future__ import annotations

import io
import json
import zipfile

import pymupdf
import pytest

from app import access, chunker, db, docx_chunks, docx_reader, extract, keyword, search, upload
from app.config import settings
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing

SENT = ("shall be hydrostatically tested at one and a half times the design pressure "
        "before the vessel is released for service.")


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "w5b525.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    install_if_missing(monkeypatch)
    db.reset_connection()
    db.init_db()
    keyword.ensure_schema()
    yield


def _structured_body() -> str:
    return (
        d.para("Piping", style="Heading1")
        + d.para("The piping class " + SENT)
        + d.para("Pipes larger than 2 inch", style="Heading2")
        + d.para("Large pipes " + SENT)
        + d.para("Each weld shall be inspected by the contractor", num=(2, 0))
        + d.para("Each repair shall be recorded in the weld log", num=(2, 0))
        + d.para("Records shall be kept for the life of the plant", num=(2, 1))
        + d.para("Flange ratings", style="Heading3")
        + d.table([["Size", "Rating", "Mass"], ["1", "150", "2.1"], ["2", "300", "3.4"],
                   ["3", "600", "5.0"]])
        + d.para("Closing remarks", style="Heading1")
        + d.para("Remarks " + SENT))


def _ingest(tmp_path, body=None, name="spec.docx", **kwargs):
    path = d.build(tmp_path / name, body if body is not None else _structured_body(),
                   footer=kwargs.pop("footer", "Company Confidential footer text"), **kwargs)
    with open(path, "rb") as fh:
        row, _job, _dup = upload.ingest(fh, name)
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    return row["id"]


def _chunks(doc_id, retrievable=None):
    sql = ("SELECT ordinal, kind, page_start, section, context, locator, retrievable, text"
           " FROM chunks WHERE document_id = ?")
    if retrievable is not None:
        sql += f" AND retrievable = {int(retrievable)}"
    return [dict(r) for r in db.connect().execute(sql + " ORDER BY ordinal", (doc_id,))]


# ------------------------------------------------------------ the reader

def test_headings_lists_tables_and_the_footer_survive_the_reader(tmp_path):
    path = d.build(tmp_path / "s.docx", _structured_body(), footer="Company Confidential footer text")
    s = docx_reader.read_structure(path)
    headings = [(b.level, b.label, b.text, b.path) for b in s.blocks if b.kind == "heading"]
    assert headings == [
        (1, "1", "Piping", ("1",)),
        (2, "1.1", "Pipes larger than 2 inch", ("1", "1.1")),
        (3, "", "Flange ratings", ("1", "1.1", "Flange ratings")),
        (1, "2", "Closing remarks", ("2",))]
    items = [(b.label, b.level, b.text) for b in s.blocks if b.kind == "list_item"]
    assert items == [("1.", 1, "Each weld shall be inspected by the contractor"),
                     ("2.", 1, "Each repair shall be recorded in the weld log"),
                     ("a)", 2, "Records shall be kept for the life of the plant")]
    [table] = [b for b in s.blocks if b.kind == "table"]
    assert len(table.rows) == 4 and all(len(r) == 3 for r in table.rows)
    assert table.rows[2] == ["2", "300", "3.4"]
    assert [(f.kind, f.text) for f in s.furniture if f.kind == "footer"] == [
        ("footer", "Company Confidential footer text")]
    assert all("Company Confidential" not in line for page in s.pages for line in page.split("\n"))


def test_list_numbers_restart_per_level_and_use_letters_and_roman_numerals(tmp_path):
    numbering = d.NUMBERING.replace(
        '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/></w:lvl>',
        '<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="(%2)"/></w:lvl>')
    body = (d.para("one", num=(2, 0)) + d.para("sub", num=(2, 1)) + d.para("sub2", num=(2, 1))
            + d.para("two", num=(2, 0)) + d.para("again sub", num=(2, 1)))
    s = docx_reader.read_structure(d.build(tmp_path / "n.docx", body, numbering=numbering))
    assert [b.label for b in s.blocks] == ["1.", "(i)", "(ii)", "2.", "(i)"]


def test_a_typed_heading_number_names_the_section_and_merged_cells_are_read(tmp_path):
    merged = ('<w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/></w:tcPr>' + d.para("Wide") +
              '</w:tc><w:tc>' + d.para("C") + '</w:tc></w:tr><w:tr><w:tc>' + d.para("a") +
              '</w:tc><w:tc>' + d.para("b") + '</w:tc><w:tc>' + d.para("c") + '</w:tc></w:tr></w:tbl>')
    body = d.para("4.2 Typed number", style="Heading3") + d.para("text under it") + merged
    s = docx_reader.read_structure(d.build(tmp_path / "t.docx", body))
    [h] = [b for b in s.blocks if b.kind == "heading"]
    assert h.path == ("4.2",) and h.text == "4.2 Typed number"
    [t] = [b for b in s.blocks if b.kind == "table"]
    assert t.rows == [["Wide", "", "C"], ["a", "b", "c"]]


def test_an_explicit_page_break_starts_a_new_reading_page(tmp_path):
    body = d.para("A", style="Heading1") + d.para("first page text", page_break=True) + d.para("second page text")
    s = docx_reader.read_structure(d.build(tmp_path / "p.docx", body))
    assert len(s.pages) == 2 and "second page text" in s.pages[1]


def test_what_is_not_read_is_reported_never_hidden(tmp_path):
    drawing = ('<w:r><w:drawing><wp:inline xmlns:wp="x"/></w:drawing></w:r>')
    body = d.para("text", raw=drawing)
    s = docx_reader.read_structure(d.build(tmp_path / "f.docx", body))
    assert any("picture" in n for n in s.notes)


def test_a_hostile_file_is_refused_by_the_reader(tmp_path):
    bomb = tmp_path / "b.docx"
    with zipfile.ZipFile(bomb, "w") as zf:
        zf.writestr("word/document.xml",
                    '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><w:document xmlns:w="x"/>')
    with pytest.raises(docx_reader.InputError) as err:
        docx_reader.read_structure(bomb)
    assert err.value.code == "doctype"


# ------------------------------------------------------------ the pipeline

def test_structure_survives_into_chunks_and_the_footer_is_not_body_text(tmp_path):
    doc = _ingest(tmp_path)
    body = _chunks(doc, retrievable=True)
    text = "\n".join(c["text"] for c in body)
    # headings, list numbers, table cells
    assert "1 Piping" in text and "1.1 Pipes larger than 2 inch" in text
    assert "1. Each weld shall be inspected" in text and "2. Each repair shall be recorded" in text
    assert "a) Records shall be kept" in text
    [table] = [c for c in body if c["kind"] == "table"]
    assert "| 2 | 300 | 3.4 |" in table["text"] and table["text"].startswith("| Size | Rating | Mass |")
    # the footer: marked, kept, never retrievable, never in the body
    assert "Company Confidential" not in text
    [footer] = [c for c in _chunks(doc) if c["kind"] == "header_footer" and c["locator"] == "footer"]
    assert footer["retrievable"] == 0 and footer["text"].startswith("[footer] ")


def test_every_body_chunk_knows_its_heading_path_and_paragraph(tmp_path):
    doc = _ingest(tmp_path)
    by_locator = {c["locator"]: c for c in _chunks(doc, retrievable=True)}
    assert "1 > para 1" in by_locator
    assert "1 > 1.1 > para 1-4" in by_locator          # paragraph 1 and the three list items
    assert "1 > 1.1 > Flange ratings > table 1" in by_locator
    assert "2 > para 1" in by_locator
    table = by_locator["1 > 1.1 > Flange ratings > table 1"]
    assert table["section"] == "Flange ratings" and "1.1 Pipes larger than 2 inch" in table["context"]
    # a Word chunk is not cited by a page
    assert db.connect().execute("SELECT pagination FROM documents WHERE id = ?", (doc,)).fetchone()[0] == "flow"


def test_a_question_about_a_table_cell_is_answered_with_the_heading_path(tmp_path):
    doc = _ingest(tmp_path)
    keyword.index_document(doc)
    # The keyword side of hybrid search (no model weights needed): the row of
    # the table, found by a word in its cells and its heading.
    result = search.search("Flange ratings Rating 300 Mass 3.4", limit=5, dense=False,
                           rerank=False, allowed_document_ids=frozenset({doc}))
    hits = result["hits"]
    assert hits, "the table chunk must be findable by a word in its cells or its heading"
    top = hits[0]
    assert top["kind"] == "table" if "kind" in top else "| 2 | 300 | 3.4 |" in top["text"]
    assert "| 2 | 300 | 3.4 |" in top["text"]
    # the citation of a Word chunk is its heading path and paragraph, not a page
    assert top["locator"] == "1 > 1.1 > Flange ratings > table 1"


def test_deleted_text_is_never_quoted_as_current_text(tmp_path):
    body = (d.para("Testing", style="Heading1")
            + d.para("Vessels " + SENT, inserted=" The test shall be witnessed by the owner.",
                     deleted=" Pressure testing is optional for small vessels."))
    doc = _ingest(tmp_path, body)
    rows = _chunks(doc)
    retrievable = "\n".join(c["text"] for c in rows if c["retrievable"])
    assert "optional" not in retrievable
    assert "The test shall be witnessed by the owner." in retrievable     # the current text
    [gone] = [c for c in rows if c["kind"] == "tracked_change" and "deleted:" in c["text"]]
    assert "Pressure testing is optional" in gone["text"] and gone["retrievable"] == 0
    assert gone["locator"] == "1 > para 1"
    # the body chunk is flagged as carrying a tracked change
    [prose] = [c for c in rows if c["kind"] == "prose"]
    assert prose["locator"].endswith(docx_chunks.TRACKED_SUFFIX)
    # search never returns the deleted words as a body hit
    keyword.index_document(doc)
    result = search.search("pressure testing is optional for small vessels", limit=5, dense=False,
                           rerank=False, allowed_document_ids=frozenset({doc}))
    assert all("optional" not in h["text"] for h in result["hits"])


def test_comments_and_the_table_of_contents_stay_beside_the_body(tmp_path):
    body = (d.para("Contents entry one", style="TOC1") + d.para("Scope", style="Heading1")
            + d.para("Scope text " + SENT, comment=0))
    doc = _ingest(tmp_path, body, comments={0: ("Ann", "Please confirm the test pressure")})
    rows = _chunks(doc)
    body_text = "\n".join(c["text"] for c in rows if c["retrievable"])
    assert "Please confirm" not in body_text and "Contents entry one" not in body_text
    kinds = {c["kind"] for c in rows if not c["retrievable"]}
    assert {"comment", "toc"} <= kinds


def test_a_pdf_of_the_same_content_still_behaves_as_before(tmp_path):
    pdf = tmp_path / "same.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in ["1 Piping", "The piping class " + SENT[:60], SENT[60:], "1.1 Pipes larger than 2 inch",
                 "Large pipes " + SENT[:60], SENT[60:]]:
        page.insert_text((72, y), line)
        y += 16
    doc.save(str(pdf))
    doc.close()
    with open(pdf, "rb") as fh:
        row, _job, _dup = upload.ingest(fh, "same.pdf")
    extract.extract_document(row["id"])
    chunker.chunk_document(row["id"])
    rows = _chunks(row["id"])
    assert rows and all(c["locator"] is None for c in rows)
    assert {c["kind"] for c in rows} <= {"prose", "table"}
    assert db.connect().execute(
        "SELECT pagination FROM documents WHERE id = ?", (row["id"],)).fetchone()[0] is None
    assert all(c["page_start"] == 1 for c in rows)


# ------------------------------------------------------------ the upload gate

def _plain_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_a_docx_is_accepted_and_queued_when_the_setting_is_on(tmp_path):
    path = d.build(tmp_path / "s.docx", _structured_body())
    with open(path, "rb") as fh:
        row, job_id, _ = upload.ingest(fh, "s.docx")
    assert row["stored_path"].endswith(".docx") and row["status"] == "queued" and job_id


def test_a_docx_is_refused_when_the_setting_is_off(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "docx_input_enabled", False)
    path = d.build(tmp_path / "s.docx", _structured_body())
    with open(path, "rb") as fh, pytest.raises(upload.UploadError) as err:
        upload.ingest(fh, "s.docx")
    assert err.value.code == "not_xlsx"


@pytest.mark.parametrize("entries,name,word", [
    ({"ppt/presentation.xml": b"<p/>", "[Content_Types].xml": b"<T/>"}, "deck.pptx", "PowerPoint"),
    ({"mimetype": b"application/vnd.oasis.opendocument.text", "content.xml": b"<c/>"}, "a.odt",
     "OpenDocument"),
])
def test_other_office_formats_are_refused_with_a_clear_message(entries, name, word):
    with pytest.raises(upload.UploadError) as err:
        upload.ingest(io.BytesIO(_plain_zip(entries)), name)
    assert err.value.code == "unsupported_office"
    assert word in err.value.message and ".docx" in err.value.message


def test_an_old_office_file_is_refused_with_a_clear_message():
    with pytest.raises(upload.UploadError) as err:
        upload.ingest(io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 old word"), "old.doc")
    assert err.value.code == "unsupported_office" and ".docx" in err.value.message


def test_a_workbook_is_still_stored_and_never_indexed(tmp_path):
    book = _plain_zip({"xl/workbook.xml": b"<w/>", "[Content_Types].xml": b"<T/>"})
    row, job_id, _ = upload.ingest(io.BytesIO(book), "crs.xlsx")
    assert row["status"] == "stored_not_indexed" and job_id is None


def test_a_hostile_docx_fails_with_a_reason_and_never_crashes_the_worker(tmp_path):
    hostile = tmp_path / "h.docx"
    with zipfile.ZipFile(hostile, "w") as zf:
        zf.writestr("word/document.xml",
                    '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><w:document '
                    'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>')
    with open(hostile, "rb") as fh:
        row, _job, _ = upload.ingest(fh, "h.docx")
    with pytest.raises(docx_reader.InputError):
        extract.extract_document(row["id"])


def test_the_document_and_its_chunks_report_the_flow_format(tmp_path):
    doc = _ingest(tmp_path)
    row = db.connect().execute("SELECT * FROM documents WHERE id = ?", (doc,)).fetchone()
    assert upload.to_api(row)["pagination"] == "flow"
    first = db.connect().execute(
        "SELECT locator FROM chunks WHERE document_id = ? AND kind = 'prose' ORDER BY ordinal",
        (doc,)).fetchone()
    assert first["locator"] == "1 > para 1"
    assert json.dumps(upload.to_api(row))     # serialisable


# ------------------------------------------------ the citation, end to end

def test_a_word_passage_is_cited_by_its_locator_in_the_prompt_and_the_source_chip(tmp_path):
    from app import answer, chat_presentation
    doc = _ingest(tmp_path)
    keyword.index_document(doc)
    hit = search.search("Flange ratings Rating 300 Mass 3.4", limit=3, dense=False, rerank=False,
                        allowed_document_ids=frozenset({doc}))["hits"][0]
    payload = answer._passage_payload(hit, "what is the rating of size 2")
    assert payload["locator"] == "1 > 1.1 > Flange ratings > table 1"
    prompt = answer._build_prompt("what is the rating of size 2", [payload])
    assert "(spec.docx, 1 > 1.1 > Flange ratings > table 1)" in prompt
    assert "page" not in prompt.split("\n")[0]
    chips = chat_presentation.sources({"answer_type": "generated", "passages": [payload],
                                       "cited": [1]})
    assert chips[0]["locator"] == "1 > 1.1 > Flange ratings > table 1"
    # a PDF passage is still cited by page
    pdf_like = {**payload, "locator": None}
    assert "spec.docx, page 1" in answer._build_prompt("q", [pdf_like])


def test_a_word_documents_datasheet_fields_are_not_read_as_a_pdf(tmp_path):
    from app import datasheets
    path = d.build(tmp_path / "ds.docx", _structured_body())
    slug, sentence, repaired = datasheets.pdf_condition(str(path))
    assert slug == "docx_fields_not_read" and "DATASHEET_OFFICE_INPUT" in sentence and not repaired


def test_the_api_lists_a_word_chunk_with_its_locator(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app
    doc = _ingest(tmp_path)
    client = TestClient(app)
    body = client.get(f"/api/documents/{doc}/chunks?retrievable=all&limit=50").json()
    locators = {c["locator"] for c in body["chunks"]}
    assert "1 > 1.1 > Flange ratings > table 1" in locators and "footer" in locators
    assert {c["kind"] for c in body["chunks"]} >= {"prose", "table", "header_footer"}
    document = client.get(f"/api/documents/{doc}").json()
    assert document["pagination"] == "flow"


def test_a_word_document_has_no_page_image(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app
    doc = _ingest(tmp_path)
    response = TestClient(app).get(f"/api/documents/{doc}/pages/1/image")
    assert response.status_code == 404
    assert "no printed pages" in json.dumps(response.json())
