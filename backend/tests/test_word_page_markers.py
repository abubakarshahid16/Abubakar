"""WORD_PAGE_MARKERS_ENABLED: a Word file's real pages, and proof that every table and
picture was read. INVENTED documents only (tests/docx_builder.py, raw OOXML). The OCR
engine is replaced by a stub: no model runs here."""

from __future__ import annotations

import dataclasses
import io
import json

import pytest
from PIL import Image

from app import (
    access,
    chunker,
    crs_blank_fields,
    crs_mapping,
    db,
    docx_chunks,
    docx_pages,
    docx_reader,
    extract,
    fts_index,
    page_ledger,
    review_audit,
    review_jobs,
    upload,
    word_flow,
    word_pages,
    word_pictures,
)
from app.config import settings
from tests import docx_builder as d
from tests.fake_tokenizer import install_if_missing

MARK = "<w:r><w:lastRenderedPageBreak/></w:r>"
BREAK = '<w:r><w:br w:type="page"/></w:r>'
LONG = "shall be hydrostatically tested at one and a half times the design pressure."
APP_NS = "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
PIC_NS = (
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
)


@pytest.fixture(autouse=True)
def temp_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "db_path", tmp_path / "pages.sqlite")
    monkeypatch.setattr(settings, "auth_mode", access.AUTH_DISABLED)
    monkeypatch.setattr(settings, "docx_input_enabled", True)
    monkeypatch.setattr(settings, "datasheet_office_input", False)
    monkeypatch.setattr(settings, "word_page_markers_enabled", True)
    install_if_missing(monkeypatch)
    word_pages._CACHE.clear()
    db.reset_connection()
    db.init_db()
    fts_index.ensure_schema()
    yield


def _para(text: str, marker: bool = False, **kwargs) -> str:
    """A paragraph with Word's saved marker in front of its text, on the new page's first line."""
    if not marker:
        return d.para(text, **kwargs)
    return f"<w:p>{MARK}{d.run(text)}</w:p>"


def _app(pages: int) -> str:
    return f'<?xml version="1.0"?><Properties xmlns="{APP_NS}"><Pages>{pages}</Pages></Properties>'


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(out, "PNG")
    return out.getvalue()


def _drawing(rid: str = "rId1") -> str:
    return (
        f'<w:r><w:drawing {PIC_NS}><a:graphic><a:graphicData><a:blip r:embed="{rid}"/>'
        "</a:graphicData></a:graphic></w:drawing></w:r>"
    )


def _rels(*targets: str) -> str:
    items = "".join(
        f'<Relationship Id="rId{i}" Type="image" Target="{t}"/>'
        for i, t in enumerate(targets, 1)
    )
    return f'<?xml version="1.0"?><Relationships>{items}</Relationships>'


def _doc(
    tmp_path,
    body: str,
    pages: int | None = None,
    extra: dict | None = None,
    name="f.docx",
):
    parts = dict(extra or {})
    if pages is not None:
        parts["docProps/app.xml"] = _app(pages)
    return d.build(tmp_path / name, body, extra=parts)


def _ingest(path) -> str:
    conn = db.connect()
    doc_id = "doc_" + path.stem
    sha = word_pictures._sha256(path)
    now = "2026-11-02T00:00:00+00:00"
    with conn:
        conn.execute(
            "INSERT INTO documents (id, filename, sha256, size_bytes, stored_path, status, uploaded_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (doc_id, path.name, sha, path.stat().st_size, str(path), "extracting", now),
        )
    return doc_id


THREE_PAGES = (
    d.para("Scope", style="Heading1")
    + d.para("First page paragraph " + LONG)
    + _para("Second page paragraph " + LONG, marker=True)
    + d.para("Third page starts after a typed break " + LONG, raw=BREAK)
    + _para("Fourth page text after the typed break " + LONG, marker=True)
)


# ------------------------------------------------------------------ real pages


def test_markers_give_each_block_its_page_and_a_typed_break_with_its_marker_counts_once(
    tmp_path,
):
    path = _doc(tmp_path, THREE_PAGES, pages=3)
    s = docx_reader.read_structure(path, picture_readings={})
    assert s.pagination.source == docx_pages.PAGES_MARKERS
    assert (s.pagination.saved_markers, s.pagination.typed_breaks) == (2, 1)
    assert s.pagination.last_page == 3
    assert len(s.pages) == 3
    # A quote cited to page N is found in page N's stored text.
    assert "First page paragraph" in s.pages[0]
    assert "Second page paragraph" in s.pages[1] and "typed break " + LONG in s.pages[1]
    assert "Fourth page text" in s.pages[2]
    assert [b.page for b in s.blocks] == [1, 1, 2, 2, 3]


def test_a_paragraph_is_on_the_page_it_starts_on_when_the_marker_is_inside_it(tmp_path):
    body = (
        f"<w:p>{d.run('Starts here ' + LONG)}{MARK}{d.run('ends there')}</w:p>"
        + d.para("Next " + LONG)
    )
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=2), picture_readings={})
    assert [b.page for b in s.blocks] == [1, 2]
    assert "ends there" in s.pages[0]


def test_a_page_with_no_text_stays_so_no_later_page_shifts(tmp_path):
    body = (
        d.para("One " + LONG)
        + f"<w:p>{MARK}{_drawing()}</w:p>"
        + _para("Three " + LONG, marker=True)
    )
    extra = {
        "word/_rels/document.xml.rels": _rels("media/a.png"),
        "word/media/a.png": "x",
    }
    s = docx_reader.read_structure(
        _doc(tmp_path, body, pages=3, extra=extra), picture_readings={}
    )
    assert len(s.pages) == 3
    assert s.pages[1] == ""
    assert "Three" in s.pages[2]


def test_no_markers_is_no_page_and_the_parts_stay_as_they_were(tmp_path):
    body = d.para("Scope", style="Heading1") + d.para("Text " + LONG)
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=4), picture_readings={})
    assert s.pagination.source == docx_pages.PAGES_NONE
    assert s.pagination.last_page == 1
    assert len(s.pages) == 1


def test_markers_short_of_words_own_count_are_partial_and_never_extrapolated(tmp_path):
    s = docx_reader.read_structure(
        _doc(tmp_path, THREE_PAGES, pages=9), picture_readings={}
    )
    assert s.pagination.source == docx_pages.PAGES_PARTIAL
    assert s.pagination.last_page == 3
    assert len(s.pages) == 3  # never the nine Word saved


def test_typed_breaks_alone_are_partial_when_word_saved_more(tmp_path):
    body = d.para("One " + LONG, page_break=True) + d.para("Two " + LONG)
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=5), picture_readings={})
    assert s.pagination.source == docx_pages.PAGES_PARTIAL
    assert [b.page for b in s.blocks] == [1, 2]


def test_markers_with_no_saved_count_are_taken_as_they_are(tmp_path):
    s = docx_reader.read_structure(_doc(tmp_path, THREE_PAGES), picture_readings={})
    assert s.pagination.source == docx_pages.PAGES_MARKERS
    assert s.pagination.word_pages is None


def test_a_marker_in_a_text_box_is_not_a_page(tmp_path):
    box = (
        f"<w:r><w:drawing {PIC_NS}><w:txbxContent><w:p>{MARK}{d.run('boxed')}</w:p>"
        "</w:txbxContent></w:drawing></w:r>"
    )
    body = f"<w:p>{d.run('One ' + LONG)}{box}</w:p>" + d.para("Still one " + LONG)
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=1), picture_readings={})
    assert [b.page for b in s.blocks] == [1, 1]
    assert s.pagination.saved_markers == 0


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc>{c}</w:tc>" for c in cells) + "</w:tr>"


def _cell(text: str, before: bool = False, after: bool = False) -> str:
    return f"<w:p>{MARK if before else ''}{d.run(text)}{MARK if after else ''}</w:p>"


def test_table_rows_keep_their_own_pages_in_the_page_text_and_the_chunks(tmp_path):
    rows = (
        _row(_cell("Size A"), _cell("Rating A"))
        + _row(_cell("one"), _cell("150"))
        + _row(_cell("two", before=True), _cell("300"))
        + _row(_cell("three"), _cell("600"))
    )
    path = _doc(tmp_path, f"<w:tbl>{rows}</w:tbl>", pages=2)
    s = docx_reader.read_structure(path, picture_readings={})
    table = s.blocks[0]
    assert table.row_pages == [1, 1, 2, 2]
    assert "one" in s.pages[0] and "two" not in s.pages[0]
    assert "three" in s.pages[1]
    chunks = docx_chunks.build_chunks(s)
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)
    assert chunks[0].row_pages[-2:] == [2, 2]


def test_one_crossing_with_markers_in_several_cells_counts_once(tmp_path):
    rows = _row(_cell("a"), _cell("b")) + _row(
        _cell("c", before=True), _cell("d", before=True)
    )
    s = docx_reader.read_structure(
        _doc(tmp_path, f"<w:tbl>{rows}</w:tbl>", pages=2), picture_readings={}
    )
    assert s.pagination.last_page == 2
    assert s.blocks[0].row_pages == [1, 2]


def test_a_row_running_over_the_page_and_the_marker_on_the_next_row_are_one_crossing(
    tmp_path,
):
    rows = (
        _row(_cell("a"), _cell("b", after=True) + _cell("b2"))
        + _row(_cell("c", before=True), _cell("d"))
        + _row(_cell("e"), _cell("f"))
    )
    s = docx_reader.read_structure(
        _doc(tmp_path, f"<w:tbl>{rows}</w:tbl>", pages=2), picture_readings={}
    )
    assert s.pagination.last_page == 2
    assert s.blocks[0].row_pages == [1, 2, 2]


def test_a_chunk_locator_names_the_real_page_and_says_partial(tmp_path):
    marked = docx_reader.read_structure(
        _doc(tmp_path, THREE_PAGES, pages=3), picture_readings={}
    )
    locators = [
        c.locator for c in docx_chunks.build_chunks(marked) if c.kind == "prose"
    ]
    assert locators[0].startswith("page")
    assert all("partial" not in x for x in locators)
    partial = docx_reader.read_structure(
        _doc(tmp_path, THREE_PAGES, pages=9), picture_readings={}
    )
    locators = [
        c.locator for c in docx_chunks.build_chunks(partial) if c.kind == "prose"
    ]
    assert "page marks partial" in locators[0]


def test_no_markers_chunk_locator_names_no_page(tmp_path):
    body = d.para("Scope", style="Heading1") + d.para("Text " + LONG)
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=4), picture_readings={})
    assert not docx_chunks.build_chunks(s)[0].locator.startswith("page")


def test_extraction_stores_real_pages_chunks_cite_them_and_a_quote_resolves(tmp_path):
    doc_id = _ingest(_doc(tmp_path, THREE_PAGES, pages=3))
    _run_job(doc_id)
    extract.extract_document(doc_id)
    conn = db.connect()
    assert (
        conn.execute(
            "SELECT pagination, page_count FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[1]
        == 3
    )
    assert (
        conn.execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = 2", (doc_id,)
        )
        .fetchone()[0]
        .startswith("Second page paragraph")
    )
    chunker.chunk_document(doc_id)
    pages = {
        r["page_no"]: r["text"]
        for r in conn.execute(
            "SELECT page_no, text FROM pages WHERE document_id = ?", (doc_id,)
        )
    }
    for chunk in conn.execute(
        "SELECT text, page_start FROM chunks WHERE document_id = ? AND kind = 'prose'",
        (doc_id,),
    ):
        first_line = chunk["text"].split("\n")[-1]
        assert first_line[:30] in "\n".join(pages.values())
        assert chunk["page_start"] in pages


def _run_job(doc_id: str) -> None:
    conn = db.connect()
    now = "2026-11-02T00:00:00+00:00"
    with conn:
        conn.execute(
            "INSERT INTO jobs (id, document_id, stage, state, started_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            ("job_" + doc_id, doc_id, "extract", "running", now, now),
        )


def test_re_reading_a_file_read_before_the_switch_leaves_no_old_part_behind(tmp_path):
    doc_id = _ingest(_doc(tmp_path, THREE_PAGES, pages=3))
    _run_job(doc_id)
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET page_count = 25 WHERE id = ?", (doc_id,))
        conn.execute(
            "INSERT INTO pages (document_id, page_no, text, char_count, needs_ocr, batch_no)"
            " VALUES (?, 25, 'old', 3, 0, 0)",
            (doc_id,),
        )
    extract.extract_document(doc_id)
    assert (
        conn.execute(
            "SELECT page_count FROM documents WHERE id = ?", (doc_id,)
        ).fetchone()[0]
        == 3
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM pages WHERE document_id = ? AND page_no > 3",
            (doc_id,),
        ).fetchone()[0]
        == 0
    )


def test_the_fact_reader_and_the_first_page_title_read_the_same_pages(tmp_path):
    body = f"<w:p>{_drawing()}</w:p>" + _para("Second " + LONG, marker=True)
    extra = {
        "word/_rels/document.xml.rels": _rels("media/a.png"),
        "word/media/a.png": "x",
    }
    path = _doc(tmp_path, body, pages=2, extra=extra)
    reading = word_flow.reading(str(path))
    assert [p.page_no for p in reading.pages] == [1, 2]
    assert "Second" in reading.pages[1].text
    # A cover holding only a picture: the title comes from the first page with words.
    assert upload._first_page_text(path).startswith("Second")


# ------------------------------------------------------------------ the CRS


def _words(pages: list[int], group: list[dict]) -> str:
    """The cell text every CRS home builds."""
    return word_pages.page_cell(f"p.{'-'.join(map(str, pages))}", pages, group)


def _finding(doc_id: str, page: int, value: str = "", **more) -> dict:
    return {
        "document_id": doc_id,
        "contractor_page": page,
        "contractor_evidence_text": value,
        "fact_id": "f1",
        **more,
    }


def test_crs_cell_shows_the_real_page_when_marks_are_complete(tmp_path):
    doc_id = _ingest(_doc(tmp_path, THREE_PAGES, pages=3))
    assert _words([2], [_finding(doc_id, 2)]) == "p.2"
    assert crs_mapping._page_section([_finding(doc_id, 2)]).startswith("p.2")


def test_crs_cell_says_partial_marks_and_a_review_note_gives_the_counts(tmp_path):
    doc_id = _ingest(_doc(tmp_path, THREE_PAGES, pages=9))
    finding = _finding(doc_id, 2)
    assert _words([2], [finding]) == "p.2 (page marks partial)"
    notes = crs_mapping.build_review_notes([finding], [])
    note = next(n for n in notes if n["note"] == word_pages.NOTE_PARTIAL_PAGES)
    assert "reach page 3" in note["detail"] and "saved 9" in note["detail"]


def test_crs_cell_with_no_markers_shows_the_heading_and_says_no_page(tmp_path):
    body = (
        d.para("Scope", style="Heading1")
        + d.para("Rated value 40 here " + LONG)
        + d.para("Testing", style="Heading1")
        + d.para("Rated value 90 there " + LONG)
    )
    doc_id = _ingest(_doc(tmp_path, body, pages=4))
    finding = _finding(doc_id, 1, "Rated value 90")
    cell = _words([1], [finding])
    assert "p.1" not in cell
    assert "Testing" in cell and "Scope" not in cell
    assert word_pages.NO_PAGE in cell
    assert crs_mapping._page_section([finding]).startswith("Section")
    # The quote not found: all that is known is the part's first heading to its last.
    unknown = _words([1], [_finding(doc_id, 1, "elsewhere")])
    assert "Scope" in unknown and "Testing" in unknown
    notes = crs_mapping.build_review_notes([finding], [])
    assert any(n["note"] == word_pages.NOTE_NO_PAGES for n in notes)


def test_crs_text_and_blank_rows_use_the_same_words(tmp_path):
    doc_id = _ingest(_doc(tmp_path, THREE_PAGES, pages=9))
    group = [_finding(doc_id, 2, origin="datasheet_check", contractor_section="Weight")]
    assert (
        crs_blank_fields.page_section(group)
        == "p.2 (page marks partial) - Fields left blank"
    )
    assert crs_blank_fields._where([2], group) == " (p.2 (page marks partial))"
    tick = crs_mapping.safety_tick_text(
        _finding(doc_id, 2, "5 kg", contractor_section="Weight")
    )
    assert "p.2 (page marks partial)," in tick


def test_every_crs_sentence_names_the_section_and_no_part_for_a_file_with_no_pages(
    tmp_path,
):
    body = d.para("Scope", style="Heading1") + d.para("Rated value 40 here " + LONG)
    doc_id = _ingest(_doc(tmp_path, body, pages=4))
    one = _finding(
        doc_id,
        1,
        "Rated value 40",
        contractor_section="Rated value",
        compliance_status="NON_COMPLIANT",
        standard_clause="1.1",
    )
    other = {**one, "contractor_evidence_text": "Rated value 40 here", "item": "B"}
    texts = {
        "reasoning": crs_mapping.reasoning_text([one]),
        "comment": crs_mapping.engineer_comment_text([one]),
        "tick": crs_mapping.safety_tick_text(one),
        "cell": crs_mapping._page_section([one]),
        "two values": crs_mapping.engineer_comment_text([one, other]),
    }
    for name, text in texts.items():
        assert "p.1" not in text, name
        assert word_pages.NO_PAGE in text, name


def test_a_pdf_finding_keeps_its_plain_page(tmp_path):
    finding = _finding("doc_not_here", 4)
    assert _words([4], [finding]) == "p.4"


def test_no_page_image_words_do_not_claim_a_word_file_has_no_pages():
    assert "no printed pages" not in word_pages.no_image_words(
        "a Word document has no printed pages"
    )


# ------------------------------------------------------------- tables, pictures


def test_tables_are_counted_from_the_file_and_an_empty_one_is_listed_not_read(tmp_path):
    nested = "<w:tbl>" + _row(_cell("inner")) + "</w:tbl>"
    body = (
        d.para("Scope", style="Heading1")
        + d.table([["a", "b"]])
        + "<w:tbl><w:tr><w:tc><w:p/></w:tc></w:tr></w:tbl>"
        + "<w:tbl><w:tr><w:tc>"
        + _cell("outer")
        + nested
        + "</w:tc></w:tr></w:tbl>"
    )
    proof = docx_reader.read_structure(
        _doc(tmp_path, body, pages=1), picture_readings={}
    ).proof
    assert (proof.tables_in_file, proof.tables_read) == (4, 3)
    assert [(n.kind, n.heading, n.reason) for n in proof.not_read] == [
        ("table", "1 Scope", docx_pages.WHY_TABLE_EMPTY)
    ]


def test_a_table_in_a_text_box_is_counted_and_said_not_read(tmp_path):
    boxed = (
        f"<w:r><w:drawing {PIC_NS}><w:txbxContent><w:tbl>{_row(_cell('x'))}</w:tbl>"
        "</w:txbxContent></w:drawing></w:r>"
    )
    proof = docx_reader.read_structure(
        _doc(tmp_path, f"<w:p>{boxed}</w:p>", pages=1), picture_readings={}
    ).proof
    assert (proof.tables_in_file, proof.tables_read) == (1, 0)
    assert proof.not_read[0].reason == docx_pages.WHY_TABLE_IN_TEXT_BOX


PICTURES = {"word/_rels/document.xml.rels": _rels("media/a.png", "media/b.emf")}


def _picture_doc(tmp_path, name="p.docx"):
    body = (
        d.para("Layout", style="Heading1")
        + f"<w:p>{d.run('Before ' + LONG)}{_drawing('rId1')}</w:p>"
        + _para("Second " + LONG, marker=True)
        + f"<w:p>{_drawing('rId2')}</w:p>"
        + "<w:tbl>"
        + _row(f"<w:p>{d.run('in a cell')}{_drawing('rId1')}</w:p>")
        + "</w:tbl>"
    )
    path = d.build(
        tmp_path / name, body, extra={**PICTURES, "docProps/app.xml": _app(2)}
    )
    import zipfile

    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("word/media/a.png", _png())
        zf.writestr("word/media/b.emf", b"\x01\x00\x00\x00not an image")
    return path


def test_a_picture_with_no_reading_is_never_counted_as_read(tmp_path):
    s = docx_reader.read_structure(_picture_doc(tmp_path), picture_readings={})
    assert (s.proof.pictures_in_file, s.proof.pictures_read) == (3, 0)
    assert [(n.no, n.page, n.heading, n.reason) for n in s.proof.not_read] == [
        (1, 1, "1 Layout", docx_pages.WHY_NOT_SENT),
        (2, 2, "1 Layout", docx_pages.WHY_NOT_SENT),
        (3, 2, "1 Layout", docx_pages.WHY_NOT_SENT),
    ]
    assert "3 of 3 picture(s) not read" in s.notes


def test_a_picture_reading_counts_and_its_text_is_on_its_page(tmp_path):
    readings = {2: docx_pages.PictureReading("Label on the drawing")}
    s = docx_reader.read_structure(_picture_doc(tmp_path), picture_readings=readings)
    assert (s.proof.pictures_in_file, s.proof.pictures_read) == (3, 1)
    assert "[picture 2, read by OCR] Label on the drawing" in s.pages[1]
    assert "Label on the drawing" not in s.pages[0]
    assert {n.no for n in s.proof.not_read} == {1, 3}


def test_a_shape_and_a_linked_picture_are_counted_and_say_why(tmp_path):
    rels = (
        '<?xml version="1.0"?><Relationships><Relationship Id="rId1" Type="image" '
        'Target="http://example.invalid/a.png" TargetMode="External"/></Relationships>'
    )
    linked = f'<w:r><w:drawing {PIC_NS}><a:blip r:link="rId1"/></w:drawing></w:r>'
    shape = f"<w:r><w:drawing {PIC_NS}><a:graphic/></w:drawing></w:r>"
    body = f"<w:p>{linked}{shape}</w:p>"
    proof = docx_reader.read_structure(
        _doc(tmp_path, body, pages=1, extra={"word/_rels/document.xml.rels": rels}),
        picture_readings={},
    ).proof
    assert proof.pictures_in_file == 2
    assert [n.reason for n in proof.not_read] == [
        docx_pages.WHY_NOT_IMAGE[docx_pages.PICTURE_LINKED],
        docx_pages.WHY_NOT_IMAGE[docx_pages.PICTURE_SHAPE],
    ]


def test_alternate_content_holds_one_picture_twice_and_counts_once(tmp_path):
    mc = 'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"'
    run = (
        f'<w:r><mc:AlternateContent {mc}><mc:Choice Requires="wps"><w:drawing/></mc:Choice>'
        "<mc:Fallback><w:pict/></mc:Fallback></mc:AlternateContent></w:r>"
    )
    proof = docx_reader.read_structure(
        _doc(tmp_path, f"<w:p>{run}</w:p>", pages=1), picture_readings={}
    ).proof
    assert proof.pictures_in_file == 1
    assert len(proof.not_read) == 1


def test_pictures_in_headers_are_counted_apart_from_the_body(tmp_path):
    header = (
        f'<?xml version="1.0"?><w:hdr xmlns:w="{d.W}"><w:p>{_drawing()}</w:p></w:hdr>'
    )
    path = _doc(
        tmp_path, d.para("Text " + LONG), pages=1, extra={"word/header1.xml": header}
    )
    proof = docx_reader.read_structure(path, picture_readings={}).proof
    assert (proof.pictures_in_file, proof.furniture_pictures) == (0, 1)


def _stub_engine(monkeypatch, answers: dict[int, str | Exception]):
    asked: list[int] = []

    def recognise(items):
        out = []
        for no, image in items:
            asked.append(no)
            answer = answers.get(no, "")
            if isinstance(answer, Exception):
                out.append((no, "", None, 0.1, f"failed: {type(answer).__name__}"))
            else:
                out.append((no, answer, 0.9, 0.1, None))
        return out

    monkeypatch.setattr(word_pictures, "_recognise", recognise)
    return asked


def test_pictures_go_to_the_local_engine_and_a_repeat_read_asks_nothing(
    tmp_path, monkeypatch
):
    path = _picture_doc(tmp_path)
    asked = _stub_engine(monkeypatch, {1: "Tank label", 3: ""})
    result = word_pictures.read_document(path)
    # Picture 2 is an EMF: not given to the engine, and said.
    assert asked == [1, 3]
    assert result == {"asked": 2, "not_readable": 1}
    stored = word_pictures.stored_readings(path)
    assert stored[1].text == "Tank label"
    assert stored[2].text == "" and "cannot be opened" in stored[2].reason
    assert stored[3].text == "" and stored[3].reason == word_pictures.WHY_NO_TEXT
    # A second read of the same bytes asks the engine nothing.
    asked.clear()
    word_pictures.read_document(path)
    assert asked == []
    # read_structure picks up what is stored, by itself.
    s = docx_reader.read_structure(path)
    assert (s.proof.pictures_in_file, s.proof.pictures_read) == (3, 1)
    assert "Tank label" in s.pages[0]
    assert {n.no: n.reason for n in s.proof.not_read}[3] == word_pictures.WHY_NO_TEXT


def test_a_failed_picture_is_not_read_and_is_asked_again(tmp_path, monkeypatch):
    path = _picture_doc(tmp_path)
    asked = _stub_engine(monkeypatch, {1: RuntimeError("x"), 3: "ok"})
    word_pictures.read_document(path)
    stored = word_pictures.stored_readings(path)
    assert stored[1].text == "" and stored[1].reason == "failed: RuntimeError"
    asked.clear()
    word_pictures.read_document(path)
    assert asked == [1]


def test_a_dead_engine_fails_the_pictures_and_not_the_document(tmp_path, monkeypatch):
    def no_pool(*_a, **_k):
        raise OSError("no process")

    monkeypatch.setattr(word_pictures.cf, "ProcessPoolExecutor", no_pool)
    path = _picture_doc(tmp_path)
    word_pictures.read_document(path)
    stored = word_pictures.stored_readings(path)
    assert stored[1].reason == "the recogniser could not run: OSError"
    assert docx_reader.read_structure(path).proof.pictures_read == 0


def test_engine_that_will_not_start_says_so_for_every_picture(monkeypatch):
    from app import ocr

    def broken():
        raise FileNotFoundError("models")

    monkeypatch.setattr(ocr, "_build_engine", broken)
    rows = word_pictures.recognise_images([(1, "a"), (2, "b")])
    assert [r[4] for r in rows] == [
        "the recogniser could not start: FileNotFoundError"
    ] * 2


def test_extraction_routes_pictures_through_the_engine_first(tmp_path, monkeypatch):
    path = _picture_doc(tmp_path)
    doc_id = _ingest(path)
    _run_job(doc_id)
    _stub_engine(monkeypatch, {1: "Tank label"})
    extract.extract_document(doc_id)
    text = (
        db.connect()
        .execute(
            "SELECT text FROM pages WHERE document_id = ? AND page_no = 1", (doc_id,)
        )
        .fetchone()[0]
    )
    assert "[picture 1, read by OCR] Tank label" in text


def test_the_ledger_and_the_audit_report_state_the_counts_and_the_list(
    tmp_path, monkeypatch
):
    path = _picture_doc(tmp_path)
    doc_id = _ingest(path)
    _run_job(doc_id)
    _stub_engine(monkeypatch, {1: "Tank label"})
    extract.extract_document(doc_id)
    chunker.chunk_document(doc_id)
    page_ledger.refresh(doc_id)
    word = page_ledger.coverage(doc_id)["word_read"]
    assert (word["tables_in_file"], word["tables_read"]) == (1, 1)
    assert (word["pictures_in_file"], word["pictures_read"]) == (3, 1)
    assert word["pages"] == 2
    assert {n["no"] for n in word["not_read"]} == {2, 3}
    section = review_audit._pages_section(doc_id)
    assert section["word_read"]["pictures_read"] == 1
    json.dumps(section)
    lines = review_audit._md_pages(section_as_audit(section))
    text = "\n".join(lines)
    assert "pictures in the file: 3; with a reading: 1" in text
    assert "tables in the file: 1; read: 1" in text
    assert "picture not read, page 2" in text


def section_as_audit(section: dict) -> dict:
    return {"pages": section}


def test_no_page_file_lists_a_not_read_picture_by_heading_never_a_part(tmp_path):
    body = d.para("Layout", style="Heading1") + f"<w:p>{_drawing()}</w:p>"
    extra = {
        "word/_rels/document.xml.rels": _rels("media/a.png"),
        "word/media/a.png": "x",
    }
    doc_id = _ingest(_doc(tmp_path, body, pages=4, extra=extra))
    word = word_pages.read_proof(doc_id)
    assert word["page_source"] == docx_pages.PAGES_NONE
    assert word["pages"] is None
    assert word["not_read"][0]["page"] is None
    assert word_pages.place(word["not_read"][0]) == "under 1 Layout"
    notes = crs_mapping.build_review_notes([_finding(doc_id, 1)], [])
    assert (
        "picture (under 1 Layout)"
        in next(n for n in notes if n["note"] == word_pages.NOTE_NOT_READ)["detail"]
    )


# ------------------------------------------------------------------ switch off


def _strip(body: str) -> str:
    return body.replace(MARK, "")


def _as_dicts(s) -> tuple:
    return (
        [dataclasses.asdict(b) for b in s.blocks],
        [dataclasses.asdict(f) for f in s.furniture],
        s.pages,
        s.notes,
    )


def test_switch_off_markers_change_nothing_and_nothing_extra_is_said(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    body = THREE_PAGES + f"<w:p>{_drawing()}</w:p>" + d.table([["a", "b"]])
    extra = {
        "word/_rels/document.xml.rels": _rels("media/a.png"),
        "word/media/a.png": "x",
    }
    marked = docx_reader.read_structure(
        _doc(tmp_path, body, pages=3, extra=extra, name="m.docx")
    )
    plain = docx_reader.read_structure(
        _doc(tmp_path, _strip(body), pages=3, extra=extra, name="p.docx")
    )
    assert _as_dicts(marked) == _as_dicts(plain)
    assert (marked.pagination, marked.proof, marked.pictures) == (None, None, [])
    assert "1 picture(s) or drawing(s) not read" in marked.notes
    # The one typed break is the only reading-part boundary, as before.
    assert len(marked.pages) == 2
    assert all(
        c.locator is None or not c.locator.startswith("page")
        for c in docx_chunks.build_chunks(marked)
    )
    assert all(b.row_pages is None for b in marked.blocks)


def test_switch_off_no_home_changes_its_words_and_no_engine_is_asked(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    path = _picture_doc(tmp_path)
    doc_id = _ingest(path)
    _run_job(doc_id)
    asked = _stub_engine(monkeypatch, {1: "x"})
    extract.extract_document(doc_id)
    assert asked == []
    assert (
        not db.connect()
        .execute("SELECT 1 FROM sqlite_master WHERE name = 'word_picture_readings'")
        .fetchone()
    )
    finding = _finding(doc_id, 1)
    assert _words([1], [finding]) == "p.1"
    assert crs_mapping.build_review_notes([finding], []) == []
    assert word_pages.read_proof(doc_id) is None
    assert word_pages.unit(doc_id) == "page"
    assert word_pages.no_image_words("said before") == "said before"
    page_ledger.refresh(doc_id)
    assert "word_read" not in page_ledger.coverage(doc_id)
    assert "word_read" not in review_audit._pages_section(doc_id)


def test_with_office_input_on_too_a_word_file_keeps_one_numbering(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "datasheet_office_input", True)
    path = _doc(tmp_path, THREE_PAGES, pages=3)
    assert (
        word_flow.applies(str(path)) is False or settings.page_read_by_reading_enabled
    )
    doc_id = _ingest(path)
    _run_job(doc_id)
    extract.extract_document(doc_id)
    row = (
        db.connect()
        .execute("SELECT pagination, page_count FROM documents WHERE id = ?", (doc_id,))
        .fetchone()
    )
    assert (row["pagination"], row["page_count"]) == ("flow", 3)


# ------------------------------------------------------------------ review of the PR


def test_no_break_at_all_is_no_page_even_when_a_stale_count_says_one(tmp_path):
    body = "".join(d.para(f"Paragraph {i} " + LONG) for i in range(400))
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=1), picture_readings={})
    assert s.pagination.source == docx_pages.PAGES_NONE
    doc_id = _ingest(_doc(tmp_path, body, pages=1, name="stale.docx"))
    assert word_pages.at(_finding(doc_id, 1)) != "p.1"
    assert word_pages.NO_PAGE[1:] in word_pages.at(_finding(doc_id, 1))


def test_no_markers_on_and_off_read_the_same_bytes(tmp_path, monkeypatch):
    body = (
        d.para("Scope", style="Heading1")
        + d.para("One " + LONG, page_break=True).replace(
            '<w:r><w:br w:type="page"/></w:r>', ""
        )
        + d.table([["a", "b"], ["1", "2"]])
    )
    path = _doc(tmp_path, body, pages=4)
    on = docx_reader.read_structure(path, picture_readings={})
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    off = docx_reader.read_structure(path)
    assert on.pagination.source == docx_pages.PAGES_NONE
    assert _as_dicts(on) == _as_dicts(off)


def _draft_row(doc_id: str, origin: str) -> dict:
    finding = _finding(
        doc_id,
        1,
        "x",
        origin=origin,
        contractor_section="Weight",
        id="fd1",
        compliance_status="NEEDS_ENGINEER_REVIEW",
        finding="Check it.",
        fact_id=None,
    )
    rows = crs_mapping.build_crs_rows([finding], [], [])
    return next(r for r in rows if r.get("finding_id") == "fd1")


@pytest.mark.parametrize("origin", [crs_mapping._AI_ORIGIN, crs_mapping._WEB_ORIGIN])
def test_draft_rows_use_the_same_page_cell(tmp_path, origin):
    partial = _ingest(_doc(tmp_path, THREE_PAGES, pages=9, name="partial.docx"))
    assert _draft_row(partial, origin)["page_section"].startswith(
        "p.1 (page marks partial)"
    )
    body = d.para("Scope", style="Heading1") + d.para("Text " + LONG)
    none = _ingest(_doc(tmp_path, body, pages=4, name="none2.docx"))
    cell = _draft_row(none, origin)["page_section"]
    assert "p.1" not in cell and word_pages.NO_PAGE in cell


def _bad_media_doc(tmp_path, rels: str, image: bytes | None, name="bad.docx"):
    import zipfile

    body = d.para("Text " + LONG) + f"<w:p>{_drawing()}</w:p>"
    path = _doc(
        tmp_path, body, pages=1, extra={"word/_rels/document.xml.rels": rels}, name=name
    )
    if image is not None:
        with zipfile.ZipFile(path, "a") as zf:
            zf.writestr("word/media/a.png", image)
    return path


def _extracts_and_says(path, monkeypatch, words: str) -> None:
    doc_id = _ingest(path)
    _run_job(doc_id)
    _stub_engine(monkeypatch, {})
    extract.extract_document(doc_id)
    row = (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc_id,))
        .fetchone()
    )
    assert row["status"] != "failed"
    reason = {n["no"]: n["reason"] for n in word_pages.read_proof(doc_id)["not_read"]}[
        1
    ]
    assert words in reason


def test_a_missing_image_is_a_reason_and_extraction_carries_on(tmp_path, monkeypatch):
    path = _bad_media_doc(tmp_path, _rels("media/gone.png"), None)
    _extracts_and_says(path, monkeypatch, "missing")


def test_a_path_outside_the_media_folder_is_refused_and_never_read(
    tmp_path, monkeypatch
):
    path = _bad_media_doc(tmp_path, _rels("../media/a.png"), None)
    import zipfile

    with zipfile.ZipFile(path, "a") as zf:
        zf.writestr("media/a.png", _png())
    asked = _stub_engine(monkeypatch, {})
    word_pictures.read_document(path)
    assert asked == []
    _extracts_and_says(path, monkeypatch, "outside")


def test_a_decompression_bomb_is_a_reason_and_extraction_carries_on(
    tmp_path, monkeypatch
):
    from PIL import Image

    path = _bad_media_doc(tmp_path, _rels("media/a.png"), _png())

    def bomb(*_a, **_k):
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr(Image, "open", bomb)
    _extracts_and_says(path, monkeypatch, "size limit")


def test_anything_else_going_wrong_with_pictures_never_fails_the_document(
    tmp_path, monkeypatch
):
    def broken(*_a, **_k):
        raise RuntimeError("no")

    path = _bad_media_doc(tmp_path, _rels("media/a.png"), _png())
    monkeypatch.setattr(word_pictures, "_read_pictures", broken)
    assert word_pictures.read_document(path)["asked"] == 0
    doc_id = _ingest(path)
    _run_job(doc_id)
    extract.extract_document(doc_id)
    assert (
        db.connect()
        .execute("SELECT status FROM documents WHERE id = ?", (doc_id,))
        .fetchone()["status"]
        != "failed"
    )


# ------------------------------------------------------------------ second review


def _boxed_marker() -> str:
    return (
        f"<w:r><w:drawing {PIC_NS}><w:txbxContent><w:p>{MARK}{d.run('boxed')}</w:p>"
        "</w:txbxContent></w:drawing></w:r>"
    )


def test_a_marker_in_a_text_box_in_a_table_cell_is_not_a_page(tmp_path):
    cell = f"<w:p>{d.run('in a cell')}{_boxed_marker()}</w:p>"
    body = f"<w:tbl>{_row(cell)}</w:tbl>" + _para("Next page " + LONG, marker=True)
    s = docx_reader.read_structure(_doc(tmp_path, body), picture_readings={})
    assert s.pagination.saved_markers == 1
    assert s.pagination.last_page == 2
    assert s.blocks[0].row_pages == [1]
    assert s.blocks[-1].page == 2


def test_a_table_in_a_text_box_in_a_cell_is_not_counted_read(tmp_path):
    boxed = (
        f"<w:r><w:drawing {PIC_NS}><w:txbxContent><w:tbl>{_row(_cell('x'))}</w:tbl>"
        "</w:txbxContent></w:drawing></w:r>"
    )
    body = f"<w:tbl>{_row(f'<w:p>{d.run(chr(97))}{boxed}</w:p>')}</w:tbl>"
    proof = docx_reader.read_structure(_doc(tmp_path, body), picture_readings={}).proof
    assert (proof.tables_in_file, proof.tables_read) == (2, 1)
    assert [n.reason for n in proof.not_read if n.kind == "table"] == [
        docx_pages.WHY_TABLE_IN_TEXT_BOX
    ]


def _section_end(text: str, kind: str | None) -> str:
    start = f'<w:type w:val="{kind}"/>' if kind else ""
    return f"<w:p><w:pPr><w:sectPr>{start}</w:sectPr></w:pPr>{d.run(text)}</w:p>"


def _sections_doc(tmp_path, first: str | None, second: str | None, name: str):
    """Two sections. A section's own type says how THAT section starts."""
    body = _section_end("One " + LONG, first) + d.para("Two " + LONG)
    path = d.build(tmp_path / name, body)
    if second:
        import zipfile

        with zipfile.ZipFile(path) as zf:
            parts = {n: zf.read(n) for n in zf.namelist()}
        parts["word/document.xml"] = parts["word/document.xml"].replace(
            b"<w:sectPr/>", f'<w:sectPr><w:type w:val="{second}"/></w:sectPr>'.encode()
        )
        with zipfile.ZipFile(path, "w") as zf:
            for n, data in parts.items():
                zf.writestr(n, data)
    return path


@pytest.mark.parametrize("kind", ["continuous", "nextColumn"])
def test_a_section_that_starts_on_the_same_page_opens_no_page(tmp_path, kind):
    path = _sections_doc(tmp_path, None, kind, "same.docx")
    s = docx_reader.read_structure(path, picture_readings={})
    assert s.pagination.last_page == 1


@pytest.mark.parametrize("kind", [None, "nextPage", "oddPage", "evenPage"])
def test_a_section_that_starts_a_page_opens_one_whatever_the_section_before_says(
    tmp_path, kind
):
    path = _sections_doc(tmp_path, "continuous", kind, "new.docx")
    s = docx_reader.read_structure(path, picture_readings={})
    assert [b.page for b in s.blocks] == [1, 2]


def test_a_column_break_is_not_a_page(tmp_path):
    body = (
        f'<w:p>{d.run("One " + LONG)}<w:r><w:br w:type="column"/></w:r></w:p>'
        + d.para("Two " + LONG)
    )
    body += d.para("Three " + LONG, page_break=True)
    s = docx_reader.read_structure(_doc(tmp_path, body), picture_readings={})
    assert s.pagination.typed_breaks == 1
    assert [b.page for b in s.blocks[:3]] == [1, 1, 1]


def test_a_heading_carried_into_a_chunk_keeps_its_own_page(tmp_path):
    body = (
        d.para("One " + LONG)
        + d.para("Layout", style="Heading1")
        + _para("Two " + LONG, marker=True)
    )
    s = docx_reader.read_structure(_doc(tmp_path, body, pages=2), picture_readings={})
    chunk = next(c for c in docx_chunks.build_chunks(s) if "Layout" in c.text)
    assert (chunk.page_start, chunk.page_end) == (1, 2)
    assert "Layout" in s.pages[chunk.page_start - 1]


def test_a_heading_with_no_real_pages_stays_as_it_was(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    body = (
        d.para("One " + LONG, page_break=True)
        + d.para("Layout", style="Heading1")
        + d.para("Two " + LONG)
    )
    s = docx_reader.read_structure(_doc(tmp_path, body))
    assert s.blocks[1].page == 2
    chunk = next(c for c in docx_chunks.build_chunks(s) if "Layout" in c.text)
    assert chunk.page_start == 2


def test_the_review_says_page_with_markers_and_part_only_without(tmp_path):
    none = _ingest(_doc(tmp_path, d.para("Text " + LONG), pages=4, name="n.docx"))
    real = _ingest(_doc(tmp_path, THREE_PAGES, pages=3, name="r.docx"))
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET pagination = 'flow'")
    assert review_jobs.document_words(none)[1] == "part"
    assert review_jobs.document_words(real)[1] == "page"


def test_switch_off_a_word_file_still_says_part(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "word_page_markers_enabled", False)
    real = _ingest(_doc(tmp_path, THREE_PAGES, pages=3, name="r.docx"))
    conn = db.connect()
    with conn:
        conn.execute("UPDATE documents SET pagination = 'flow'")
    assert review_jobs.document_words(real)[1] == "part"


def test_the_procedure_page_cell_uses_the_same_words(tmp_path, monkeypatch):
    from app import procedure_crs

    monkeypatch.setattr(settings, "procedure_crs_fields_enabled", True)
    for pages, want in ((9, "p.2 (page marks partial)"), (3, "p.2")):
        doc_id = _ingest(
            _doc(tmp_path, THREE_PAGES, pages=pages, name=f"proc{pages}.docx")
        )
        _run_job(doc_id)
        extract.extract_document(doc_id)
        row = {
            "quote": "Second page paragraph " + LONG,
            "page_section": "p.1 (page marks partial) - Scope",
        }
        procedure_crs.fill_pages([row], [], doc_id)
        assert row["page_section"] == f"{want} - Scope"
    body = d.para("Scope", style="Heading1") + d.para("Second page paragraph " + LONG)
    none = _ingest(_doc(tmp_path, body, pages=4, name="procn.docx"))
    _run_job(none)
    extract.extract_document(none)
    row = {"quote": "Second page paragraph " + LONG, "page_section": ""}
    procedure_crs.fill_pages([row], [], none)
    assert "p.1" not in row["page_section"]
    assert word_pages.NO_PAGE in row["page_section"]
    first = row["page_section"]
    procedure_crs.fill_pages([row], [], none)
    assert row["page_section"] == first
